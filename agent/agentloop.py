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
# agentloop.py -- import 区加一行
from .persist.persister import Persister



def _run_steps(state: AgentState, context: RuntimeContext, persister):
    """Agent 主循环体（共享给 agentloop 正常 run 与 continue_loop 续跑）。
    假设 state.messages 已初始化（正常 run 由 agentloop 初始化；resume 由 resume() 重建）。"""
    config = context.config
    sink = context.sink
    loop_detector = LoopDetector(threshold=config.soft_stop_threshold)
    tools = [tool.tool_spec for tool in context.registry.list_tools()]

    while state.should_continue():
        step = state.new_step()
        sink.emit(StepStart(step_index=step.index))
        step.deadline = time.perf_counter() + config.step_timeout

        try:
            model_request = ModelRequest(
                messages=state.messages,
                tools=tools if context.config.enable_tools else [],
                model=context.config.model,
                temperature=context.config.temperature,
                max_tokens=context.config.max_tokens,
            )
            step.model_request = model_request
            model_response = context.model_adapter.stream_llm(model_request, sink)
            step.model_response = model_response

            # durability-first：先落盘（decide 前，FINISH/tool_call 两路都保住付费 LLM 回复）
            if persister:
                persister.log_assistant(model_response)

            action = decide(model_response)
            if action == Action.FINISH:
                # final 也进 messages 作历史（推翻 Decision 3：多轮对话需要上一轮最终回复作上下文，
                # 否则下一轮 model 看不到、重复回答）。final_response 仍设，给 _emit_run_end 取 final_text。
                state.messages = context.model_adapter.append_assistant(state.messages, model_response)
                state.complete(model_response)
                step.finish()
                sink.emit(StepEnd(step_index=step.index))
                return state
            if action == Action.HANDLE_ERROR:
                raise ValueError("模型返回既无文本也无工具调用")

            # CALL_TOOLS：先 append_assistant（解耦：assistant 单独 append，同 CC）
            state.messages = context.model_adapter.append_assistant(state.messages, model_response)
            state.transition("waiting_tool")

            # 逐 result 增量：durability-first（log-then-append），按完成序 yield
            tool_results = []
            for r in context.tool_executor.execute_many(
                model_response.tool_calls, timeout=config.step_timeout, sink=sink
            ):
                if persister:
                    persister.log_tool_result(r)
                state.messages = context.model_adapter.append_tool_result(state.messages, r)
                step.tool_results.append(r)      # 对称：live 也填 step.tool_results（与 replay 一致）
                state.tool_history.append(ToolHistoryEntry(
                    call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
                    error_type=r.error.get("type") if r.error else None))
                tool_results.append(r)

            state.transition("running")

            # 失败兜底 / 循环检测（收完本轮所有 result 再判）
            if any(not r.ok for r in tool_results):
                state.record_error()
                if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                    state.fail({"type": "ToolFailure",
                                "message": f"连续工具调用失败次数{state.consecutive_tool_failures}超过阈值{config.max_consecutive_tool_failures}"})
                    sink.emit(StepEnd(step_index=step.index))
                    return state
            else:
                state.reset_error()
                loop_detector.observe(model_response.tool_calls)
                if loop_detector.is_looping():
                    state.messages.append(Message(
                        role="user",
                        content=SOFT_STOP_HINT.format(step=step.index, tool=tool_results[0].tool_name),
                    ))
                    loop_detector.reset()

            sink.emit(StepEnd(step_index=step.index))

        except Exception as e:
            error = classify_error(e)
            step.error = error
            step.finish()
            sink.emit(StepEnd(step_index=step.index))

            if not error["retryable"]:
                state.fail(error)
                return state
            state.record_error()
            if state.consecutive_tool_failures >= config.max_consecutive_tool_failures:
                state.fail(error)
                return state
            state.messages.append(Message(
                role="user",
                content=f"[系统提示] 上一步执行失败：{error['type']}: {error['message']}。"
                        f"请根据错误信息调整下一步，或直接给出最终答案。",
            ))
            # 可重试且未超阈值：继续下一轮（StepEnd 已发）

    if not state.is_terminal():
        state.exceed_max_steps()
    return state
def _run_turn(user_input: str, state: AgentState, context: RuntimeContext, persister):
    """单轮体（agentloop 与 REPL 复用）：初始化 messages + log_user + _run_steps。
    不发 RunEnd、不收尾 persister——收尾由调用方负责（agentloop 走 _end_run；REPL 走 session 级收尾）。"""
    config = context.config
    # 1. 初始化对话消息：首轮(system+user)；续轮(只 append user，保留跨轮上下文)
    #    判据：state.messages 是否为空——空=首轮，非空=续轮(已有跨轮历史)
    if not state.messages and config.system_prompt:
        state.messages.append(Message(role="system", content=config.system_prompt))
    state.messages.append(Message(role="user", content=user_input))
    if persister:
        persister.log_user(user_input)     # durability-first：先落盘再改内存
    # 2. 主循环（抽到 _run_steps，与 continue_loop 共享）
    return _run_steps(state, context, persister)

def _emit_run_end(state: AgentState, sink):
    """发 RunEnd 流式事件（UI 用）。final_text 从 final_response 取。"""
    final_text = None
    if state.final_response is not None:
        final_text = getattr(state.final_response, "text", None)
    sink.emit(RunEnd(status=state.status, error=state.error, final_text=final_text))

def _end_run(state: AgentState, sink, persister):
    """单次调用收尾：发 RunEnd + log_run_end + close（agentloop / continue_loop 复用）。"""
    _emit_run_end(state, sink)
    if persister:
        persister.log_run_end(state.status, state.error)
        persister.close()

def _execute_pending(state: AgentState, context: RuntimeContext, persister):
    """resume 后执行 pending_tool_calls（崩在执行中的工具，per-call_id）。
    用录好的 tool_calls，不调 LLM；结果归到末尾 step（同一轮 assistant 的工具）。"""
    config = context.config
    sink = context.sink
    pending = state.pending_tool_calls
    state.pending_tool_calls = []
    if not pending:
        return
    step = state.steps[-1] if state.steps else state.new_step()
    if state.status != "running":
        state.transition("running")        # created -> running（resume 后可能仍是 created）
    state.transition("waiting_tool")
    for r in context.tool_executor.execute_many(pending, timeout=config.step_timeout, sink=sink):
        if persister:
            persister.log_tool_result(r)
        state.messages = context.model_adapter.append_tool_result(state.messages, r)
        step.tool_results.append(r)
        state.tool_history.append(ToolHistoryEntry(
            call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
            error_type=r.error.get("type") if r.error else None))
    state.transition("running")


def continue_loop(state: AgentState, context: RuntimeContext) -> AgentState:
    """resume 续跑：state.messages 已由 resume() 重建，跳过初始化。
    先执行 pending（崩在工具执行中），再进主循环。Persister 以 append 模式复用同一 transcript。"""
    sink = context.sink
    persister = Persister(state.run_id) if context.persist else None
    sink.emit(RunStart(run_id=state.run_id))
    # 续跑重置步数计数：max_steps 是单轮上限，重放出的历史 steps 不该吃掉续跑预算。
    # steps 保留为历史轨迹（审计/重放），step_index 仅控制"还能跑几步"。
    state.step_index = 0
    _execute_pending(state, context, persister)
    state = _run_steps(state, context, persister)
    _end_run(state, sink, persister)
    return state

def agentloop(user_input: str, context: RuntimeContext) -> AgentState:
    """运行 Agent 主循环（流式版 + 可选消息级落盘）。单次调用自洽：
    自建 Persister、结束写 run_end + close。REPL 多轮复用走 _run_turn，不经过这里。"""
    config = context.config or AgentConfig()
    state = context.state or AgentState(max_steps=config.max_steps)
    sink = context.sink
    persister = Persister(state.run_id) if context.persist else None

    sink.emit(RunStart(run_id=state.run_id))
    state = _run_turn(user_input, state, context, persister)
    _end_run(state, sink, persister)
    return state


def run_agent_loop(registry: ToolRegistry, model_adapter: BaseModelAdapter, tool_executor: ToolExecutor, config: Optional[AgentConfig] = None):
    import sys
    import uuid
    from .streaming.printer import StreamingPrinter
    # Windows 默认 stdout 可能是 GBK，无法编码 ⏺/⎿ 等符号；切到 UTF-8（VS Code 终端原生支持）。
    # 失败也不影响（printer 内部还有 encode 兜底）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    printer = StreamingPrinter()
    config = config or AgentConfig()
    # 会话级单 run_id（对齐 CC）：整个 REPL session 共用一个 transcript.jsonl，跨轮 append；
    # 退出时才写 run_end。崩在中途无 run_end -> resume 按最后状态续跑（durability-first 的保证）。
    session_run_id = str(uuid.uuid4())
    messages: list = []               # 跨轮累积上下文（内存共享 list）
    persister = Persister(session_run_id)
    last_state = None
    try:
        while True:
            user_input = input("User: ")
            if user_input.lower() in ["exit", "quit"]:
                print("Exiting agent loop.")
                break
            # 每轮新 state（step_index 从 0，max_steps 是单轮上限），但共用 run_id + messages
            state = AgentState(run_id=session_run_id, max_steps=config.max_steps)
            state.session_id = session_run_id
            state.messages = messages     # 继承跨轮上下文（首轮空，_run_turn 加 system）
            context = RuntimeContext(
                registry=registry,
                model_adapter=model_adapter,
                tool_executor=tool_executor,
                config=config,
                state=state,
                sink=printer,
                persist=True,
            )
            # 文本/工具进度已在运行中由 StreamingPrinter 实时流式打印。
            # _run_turn 往 state.messages append user(in-place)；但 append_assistant/tool_result 返回
            # 新 list(copy)，state.messages 会离开共享 messages 对象，故每轮结束用 messages = state.messages
            # 同步（见下），否则下一轮丢失上一轮 assistant + tool_result（bug2）。
            printer.emit(RunStart(run_id=session_run_id))
            state = _run_turn(user_input, state, context, persister)
            _emit_run_end(state, printer)   # 每轮 UI 结束提示；不 log_run_end（session 级，退出时才写）
            messages = state.messages   # 同步共享 list（append 返回 copy，state.messages 已离开原对象）
            last_state = state
        # session 正常退出：写 run_end（用最后一轮 status）；崩在 finally 前则不写 -> resume 续跑
        if last_state is not None:
            persister.log_run_end(last_state.status, last_state.error)
    finally:
        persister.close()

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