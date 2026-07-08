from dataclasses import dataclass, field
import time
from typing import Any, Optional

from .core.errors import classify_error

from .control.actions import Action, decide

from .prompts import SOFT_STOP_HINT

from .control.loop_detector import LoopDetector

from .config.config import AgentConfig
from .config.provider import load_provider_config, make_adapter
from .core.state import AgentState, ToolHistoryEntry

from .adapters.base import BaseModelAdapter
from .core.models import ModelRequest
from .core.messages import Message
from .runtime import RuntimeContext
from .tools.registry import ToolExecutor, ToolRegistry
from .streaming.events import RunStart, StepStart, StepEnd, RunEnd

def agentloop(
    user_input: str,
    context: RuntimeContext,
) -> AgentState:
    """
    运行 Agent 主循环（流式版）。

    流程：
    1. 接收用户输入，封装成初始 Message。
    2. 从 ToolRegistry 导出可用工具的 ToolSpec。
    3. 进入最多 max_steps 轮 Agent 循环：
       - 流式调用 LLM（stream_llm）：逐 token 文本与工具参数增量实时推给 sink；
       - 若模型无 tool_calls -> 最终回答，结束；
       - 若返回 tool_calls -> 执行工具（ToolStart/ToolEnd 进度也推给 sink），结果回填，下一轮。
    4. 超过 max_steps 仍未结束，标记 max_steps_exceeded。

    sink（context.sink）是流式事件汇入点；默认 NullSink，对编程式调用/测试透明。
    """
    config = context.config or AgentConfig()
    state = context.state or AgentState(max_steps=config.max_steps)
    sink = context.sink
    loop_detector = LoopDetector(threshold=config.soft_stop_threshold)

    sink.emit(RunStart(run_id=state.run_id))

    # 1. 初始化对话消息（system prompt 放第一条，定义 Agent 的行为契约）
    state.messages = []
    if config.system_prompt:
        state.messages.append(
            Message(role="system", content=config.system_prompt)
        )
    state.messages.append(Message(role="user", content=user_input))

    # 2. 从 registry 导出工具定义
    # 这里假设每个 Tool 内部都有 tool_spec 字段
    tools = [
        tool.tool_spec
        for tool in context.registry.list_tools()
    ]

    # 3. 多轮 Agent Loop
    while state.should_continue():
        step = state.new_step()
        sink.emit(StepStart(step_index=step.index))

        step.deadline = time.perf_counter() + config.step_timeout  # 记录本轮执行截止时间
        # 4. 构造本轮模型请求
        try:
            model_request = ModelRequest(
                messages=state.messages,
                tools=tools if context.config.enable_tools else [],
                model=context.config.model,
                temperature=context.config.temperature,
                max_tokens=context.config.max_tokens,
            )
            step.model_request = model_request
            # 5. 流式调用模型：边收边把增量事件推给 sink，返回累积好的 ModelResponse。
            #    文本 token 与工具参数增量此时已实时呈现给用户。
            #    异常（超时/认证/限流）原样抛出，交由下面的 classify_error 处理。
            model_response = context.model_adapter.stream_llm(model_request, sink)
            step.model_response = model_response

            # 6. 如果模型没有请求工具调用，说明已经得到最终回答
            action = decide(model_response)
            if action == Action.FINISH:
                state.complete(model_response)
                step.finish()
                sink.emit(StepEnd(step_index=step.index))
                sink.emit(RunEnd(status="completed", final_text=model_response.text))
                return state
            if action == Action.HANDLE_ERROR:
                raise ValueError("模型返回既无文本也无工具调用")  # 走下面的错误回填

            # 7. 执行当前轮模型返回的所有工具调用
            # action == CALL_TOOLS：executor 边执行边发 ToolStart/ToolEnd（每个包 timeout）
            state.transition("waiting_tool")  # 进入等待工具执行状态
            tool_results = context.tool_executor.execute_many(
                model_response.tool_calls, timeout=config.step_timeout, sink=sink
            )

            # 8. 将本轮 assistant tool_calls 和 tool_results 回填到 messages
            # 注意：具体怎么组织 OpenAI / Claude / DeepSeek 的消息格式，
            # 应该交给 model_adapter.append_tool_results 处理
            state.messages = context.model_adapter.append_tool_results(
                messages=state.messages,
                model_response=model_response,
                tool_results=tool_results,
            )

            # 工具调用摘要写入 tool_history（只存 call_id/ok/error_type，防状态膨胀；完整轨迹在 steps）
            for r in tool_results:
                state.tool_history.append(ToolHistoryEntry(
                    call_id=r.call_id,
                    tool_name=r.tool_name,
                    ok=r.ok,
                    error_type=r.error.get("type") if r.error else None,
                ))

            state.transition("running")  # 工具执行完毕，回到 running 状态

            # 失败兜底 成功循环检测
            if any(not r.ok for r in tool_results):
                state.record_error()  # 记录本轮工具调用失败，连续失败计数加1
                if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                    state.fail({"type": "ToolFailure",
                                "message": f"连续工具调用失败次数{state.consecutive_tool_failures}超过阈值{config.max_consecutive_tool_failures}"})
                    sink.emit(StepEnd(step_index=step.index))
                    sink.emit(RunEnd(status="failed", error=state.error))
                    return state
            else:
                state.reset_error()  # 本轮工具调用成功，连续失败计数清零

                loop_detector.observe(model_response.tool_calls)

                if loop_detector.is_looping():
                    state.messages.append(Message(
                        role="user",
                        content=SOFT_STOP_HINT.format(step=step.index, tool=tool_results[0].tool_name),
                    ))
                    loop_detector.reset()  # 重置循环检测器，避免重复注入软终止提示

            # 本轮正常结束，进入下一轮
            sink.emit(StepEnd(step_index=step.index))

        except Exception as e:
            error = classify_error(e)
            step.error = error
            step.finish()
            sink.emit(StepEnd(step_index=step.index))

            # 不可重试（认证/参数/配置）：重试必失败，直接 fail，不回填模型、不浪费步数
            if not error["retryable"]:
                state.fail(error)
                sink.emit(RunEnd(status="failed", error=error))
                return state

            # 可重试：回填给模型当 observation，让模型调整；连续失败超阈值才 fail
            state.record_error()
            if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                state.fail(error)
                sink.emit(RunEnd(status="failed", error=error))
                return state
            state.messages.append(
                Message(
                    role="user",
                    content=f"[系统提示] 上一步执行失败：{error['type']}: {error['message']}。"
                            f"请根据错误信息调整下一步，或直接给出最终答案。",
                )
            )
            # 可重试且未超阈值：继续下一轮（StepEnd 已发）

    if not state.is_terminal():
        # Agent 循环超过最大步数，标记为失败
        state.exceed_max_steps()

    sink.emit(RunEnd(status=state.status, error=state.error))
    return state

def run_agent_loop(registry: ToolRegistry, model_adapter: BaseModelAdapter, tool_executor: ToolExecutor, config: Optional[AgentConfig] = None):
    import sys
    from .streaming.printer import StreamingPrinter
    # Windows 默认 stdout 可能是 GBK，无法编码 ⏺/⎿ 等符号；切到 UTF-8（VS Code 终端原生支持）。
    # 失败也不影响（printer 内部还有 encode 兜底）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    printer = StreamingPrinter()
    while True:
        user_input = input("User: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Exiting agent loop.")
            break
        context = RuntimeContext(
            registry=registry,
            model_adapter=model_adapter,
            tool_executor=tool_executor,
            config=config or AgentConfig(),
            state=AgentState(),
            sink=printer,
        )
        # 文本/工具进度已在运行中由 StreamingPrinter 实时流式打印，
        # 这里不再事后 print（避免重复输出）。
        agentloop(user_input, context)

def main():
    # 用 tools 子包的默认 registry：@tool 装饰器把 getnowtime 注册到了那里
    import agent.tools
    registry = agent.tools.registry
    # 默认用 openai_compatible(DeepSeek)；切豆包改 "ark"
    pc = load_provider_config("ark")
    if not pc.api_key:
        raise SystemExit("未设置 DEEPSEEK_API_KEY，请在 code/.env 配置 DEEPSEEK_API_KEY/BASE_URL/MODEL")
    model_adapter = make_adapter(pc)
    tool_executor = ToolExecutor(registry)
    # 用 provider 配置里的 model（DEEPSEEK_MODEL）覆盖 AgentConfig 默认的 deepseek-v4-pro，
    # 否则 agentloop 会把 context.config.model 直接发给 API，provider 的 model 形同虚设。
    run_agent_loop(registry, model_adapter, tool_executor, config=AgentConfig(model=pc.model))
if __name__ == "__main__":
    main()