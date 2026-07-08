from dataclasses import dataclass, field
import time
from typing import Any, Optional
 
from .core.errors import classify_error

from .control.actions import Action, decide

from .control.timeout import call_with_timeout
from .prompts import SOFT_STOP_HINT

from .control.loop_detector import LoopDetector

from .config.config import AgentConfig
from .config.provider import load_provider_config, make_adapter
from .core.state import AgentState

from .adapters.base import BaseModelAdapter
from .core.models import ModelRequest
from .core.messages import Message
from .runtime import RuntimeContext
from .tools.registry import ToolExecutor, ToolRegistry

def agentloop(
    user_input: str,
    context: RuntimeContext,
) -> AgentState:
    """
    运行 Agent 主循环。

    流程：
    1. 接收用户输入，并封装成初始 Message。
    2. 从 ToolRegistry 中导出当前可用工具的 ToolSpec。
    3. 进入最多 max_steps 轮 Agent 循环。
    4. 每一轮都把当前 messages 和 tools 发送给模型。
    5. 如果模型没有返回 tool_calls，说明模型已经生成最终回答，直接返回。
    6. 如果模型返回 tool_calls，则由 ToolExecutor 执行这些工具调用。
    7. 将 assistant 的工具调用信息和工具执行结果一起回填到 messages。
    8. 进入下一轮，让模型基于工具结果继续推理。
    9. 如果超过 max_steps 仍未结束，则抛出异常，防止死循环。
    """
    config = context.config or AgentConfig()
    state = context.state or AgentState(max_steps=config.max_steps)
    loop_detector = LoopDetector(threshold=config.soft_stop_threshold)
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
        step=state.new_step()

        step.deadline = time.perf_counter() + config.step_timeout  # 记录本轮执行截止时间
        # 4. 构造本轮模型请求
        try:
            model_request = ModelRequest(
            messages=state.messages,
            tools=tools if context.config.enable_tools else [],
            model=context.config.model,
            temperature=context.config.temperature,
            max_tokens=context.config.max_tokens,)
            step.model_request = model_request
            # 5. 调用模型 
            # model_response = context.model_adapter.call_llm(model_request)
            model_response = call_with_timeout(
                context.model_adapter.call_llm, model_request,
                timeout=config.step_timeout,
            )
            
            step.model_response = model_response
            # 6. 如果模型没有请求工具调用，说明已经得到最终回答
            action = decide(model_response)
            if action == Action.FINISH:
                state.complete(model_response)
                step.finish()
                return state
            if action == Action.HANDLE_ERROR:
                raise ValueError("模型返回既无文本也无工具调用")  # 走下面的错误回填


            # 7. 执行当前轮模型返回的所有工具调用
            # action == CALL_TOOLS：执行工具，每个包 timeout
            state.transition("waiting_tool")  # 进入等待工具执行状态
            tool_results = context.tool_executor.execute_many(
                model_response.tool_calls, timeout=config.step_timeout
            )
            print(f"[DEBUG] tool_results: {tool_results}")
            # 8. 将本轮 assistant tool_calls 和 tool_results 回填到 messages
            # 注意：具体怎么组织 OpenAI / Claude / DeepSeek 的消息格式，
            # 应该交给 model_adapter.append_tool_results 处理
            state.messages = context.model_adapter.append_tool_results(
                messages=state.messages,
                model_response=model_response,
                tool_results=tool_results,
            )

            # TODO:这里要把工具进行压缩放到tool_history里，避免每轮都把工具调用结果塞到messages里，导致上下文膨胀

            state.transition("running")  # 工具执行完毕，回到 running 状态

            # 失败兜底 成功循环检测
            if any(not r.ok for r in tool_results):
                state.record_error()  # 记录本轮工具调用失败，连续失败计数加1
                if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                    state.fail({"type":"ToolFailure",
                                "message":f"连续工具调用失败次数{state.consecutive_tool_failures}超过阈值{config.max_consecutive_tool_failures}"})
                    return state
            else:
                state.reset_error()  # 本轮工具调用成功，连续失败计数清零

                loop_detector.observe(model_response.tool_calls)

                if loop_detector.is_looping():
                    state.messages.append(Message(
                        role="user",
                        content=SOFT_STOP_HINT.format(step=step.index,tool=tool_results[0].tool_name),
                    ))
                    loop_detector.reset()  # 重置循环检测器，避免重复注入软终止提示
                
        except Exception as e:
            error = classify_error(e)
            step.error = error
            step.finish()

            # 不可重试（认证/参数/配置）：重试必失败，直接 fail，不回填模型、不浪费步数
            if not error["retryable"]:
                state.fail(error)
                return state

            # 可重试：回填给模型当 observation，让模型调整；连续失败超阈值才 fail
            state.record_error()
            if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                state.fail(error)
                return state
            state.messages.append(
                Message(
                    role="user",
                    content=f"[系统提示] 上一步执行失败：{error['type']}: {error['message']}。"
                            f"请根据错误信息调整下一步，或直接给出最终答案。",
                )
            )

    if not state.is_terminal():
    
        # Agent 循环超过最大步数，标记为失败
    
        state.exceed_max_steps()

    return state

def run_agent_loop(registry: ToolRegistry, model_adapter: BaseModelAdapter, tool_executor: ToolExecutor, config: Optional[AgentConfig] = None):
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
            state=AgentState()
        )
        state = agentloop(user_input, context)
        if state.error:
            print(f"Agent encountered an error: {state.error}")
        elif state.final_response is not None:
            print(f"Agent: {state.final_response.text}")

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