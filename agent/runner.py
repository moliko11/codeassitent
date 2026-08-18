# agent/runner.py - Agent 主循环执行体(核心 loop 机制)
#
# 拆自 agentloop.py(它从 ~780 行瘦身):把"跑一轮 / 跑主循环 / 跑三种模式 / 跑子 agent / 发事件"
# 这些 loop 机制抽到独立模块,让 multiagent.Agent.run 直接依赖本模块而不是 agentloop
# (agentloop 还装着 REPL/入口/run_meta 持久化,是 UI + 编排层)。
#
# 打破 agentloop <-> multiagent 循环引用(原靠函数内延迟 import 压住):
#   - multiagent -> runner(模块级,agent.run 拿 _run_turn)
#   - runner 的 _run_subagent 只在运行期延迟 import multiagent(被调用时才需要,模块加载无环)
# 依赖方向:runner -> {core, control, context, tools, prompts, ...}(向下),无反向。
import asyncio
import sys
import time
import uuid
from dataclasses import replace

from .core.errors import classify_error
from .control.actions import Action, decide
from .prompts import SOFT_STOP_HINT, build_system_prompt
from .control.loop_detector import LoopDetector
from .control.planner import Planner
from .control.critic import Critic
from .config.loader import build_context_builder_params
from .core.state import AgentState, ToolHistoryEntry
from .core.models import ModelRequest
from .core.messages import Message
from .runtime import RuntimeContext
from .tools.defs import ToolResult
from .streaming.events import StepStart, StepEnd, RunEnd, AssistantMessage, ToolResultMessage
from .persist.persister import Persister
from .context.builder import ContextBuilder
from .context.auto_compact import make_summarizer
from .tools import _runtime_state
from .tools.settings import t as _tool_cfg


# ─────────────────── 事件发射(源头发消息级/工具结果,web 契约)───────────────────

def _emit_assistant_message(sink, state, model_response, step):
    """源头发完整 assistant 消息(对齐 CC `assistant`):ModelResponse 已全量,不做 delta 聚合。

    数据就绪点:stream_llm 返回后(此处 text/thinking/tool_calls/usage/stop_reason 全在)。
    tool_calls 转纯 dict(事件层不反向依赖 ToolCall);agent_id 打标(子 agent 可区分)。
    """
    tool_calls = tuple({
        "call_id": tc.call_id, "tool_name": tc.tool_name, "arguments": tc.arguments,
    } for tc in (model_response.tool_calls or []))
    sink.emit(AssistantMessage(
        run_id=state.run_id, uuid=str(uuid.uuid4()),
        agent_id=_runtime_state.agent_id.get(),
        step_index=step.index,
        text=model_response.text or "",
        thinking=model_response.thinking or "",
        tool_calls=tool_calls,
        stop_reason=model_response.stop_reason,
        usage=model_response.usage,
    ))


def _emit_tool_result_message(sink, state, r):
    """源头发完整工具结果(对齐 CC `user` 的 tool_result 块):ToolResult 就绪即发。

    在 async-for 逐 result 处调(含 subagent 替换后的最终 r)。elapsed_ms 由
    _parallel.run_one 实测填入 ToolResult(ToolEnd 同源,修待办 C 恒 0)。
    """
    sink.emit(ToolResultMessage(
        run_id=state.run_id, uuid=str(uuid.uuid4()),
        call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
        summary=(r.text or "")[:300] or None,
        elapsed_ms=getattr(r, "elapsed_ms", 0.0),
        attempts=(r.meta or {}).get("attempts", 1),
        error_type=(r.error or {}).get("type") if r.error else None,
        agent_id=_runtime_state.agent_id.get(),
    ))


def _emit_run_end(state: AgentState, sink):
    """发 RunEnd 流式事件（UI 用）。final_text 从 final_response 取。

    usage/duration_ms/num_steps = 本轮聚合统计(对齐 CC `result` 事件):
    usage 来自 state.token_*（_run_steps 每条 ModelResponse.usage 累加,不含子 agent);
    前端/CLI 只在 turn 结束显示总账,不在每条 assistant 消息上显示 per-step usage。
    """
    final_text = None
    if state.final_response is not None:
        final_text = getattr(state.final_response, "text", None)
    usage = None
    if state.token_total or state.token_input or state.token_output:
        usage = {"input_tokens": state.token_input, "output_tokens": state.token_output,
                 "total_tokens": state.token_total, "cached_tokens": state.token_cached}
    duration_ms = None
    if state.steps and state.steps[0].started_at is not None:
        ends = [s.ended_at for s in state.steps if s.ended_at is not None]
        if ends:
            duration_ms = round((max(ends) - state.steps[0].started_at) * 1000, 2)
    sink.emit(RunEnd(status=state.status, error=state.error, final_text=final_text,
                     usage=usage, duration_ms=duration_ms, num_steps=len(state.steps)))


# ─────────────────── 主循环体 ───────────────────

async def _run_steps(state: AgentState, context: RuntimeContext, persister, subtask: bool = False):
    """Agent 主循环体（共享给 agentloop 正常 run / continue_loop 续跑 / plan_execute 子任务）。
    假设 state.messages 已初始化（正常 run 由 agentloop 初始化；resume 由 resume() 重建）。
    subtask=True(plan_execute 子任务):FINISH 时不 complete(保持 running),只设 final_response;
    超 max_steps 不转终态,回填提示让外层 plan_execute 继续下一步(对齐 stage7-plan §3.3)。"""
    config = context.config
    sink = context.sink
    loop_detector = LoopDetector(threshold=config.soft_stop_threshold)
    all_tools = context.registry.list_tools()
    allowed = config.allowed_tools
    # 按 tools.yaml <name>.enabled 过滤(默认 true);web_fetch.enabled=false 时不给模型看到/调用。
    # configure_tools 未调(测试)时 _CFG=None -> 全回落 True,行为不变。
    def _tool_enabled(name: str) -> bool:
        return bool(_tool_cfg(f"{name}.enabled", True))
    if allowed:
        # 白名单:只给模型看 allowed_tools 内的工具(权限隔离,题16;commit 10)
        tools = [t.tool_spec for t in all_tools
                 if t.tool_spec.name in allowed and _tool_enabled(t.tool_spec.name)]
    else:
        # 空=全允许(单 agent 默认);但 handoff 是特权工具(orchestrator 委派用),不自动放开,
        # 防子 agent 递归调子 agent(子 agent 无权再 handoff)。单 agent 不注册 handoff,此处无影响。
        tools = [t.tool_spec for t in all_tools
                 if t.tool_spec.name != "handoff" and _tool_enabled(t.tool_spec.name)]

     # 阶段 6：ContextBuilder(调 LLM 前组装 messages 的入口，对齐 cc query.ts:365 的管线入口)。
    # context_builder 未注入时从 config 现场构造；超 budget 只 print 到 stderr 告警，不裁剪。
    builder = context.context_builder or ContextBuilder(
        context_budget=config.context_budget,
        warn_sink=lambda m: print(m, file=sys.stderr),
        summarizer=make_summarizer(context.model_adapter),  # 步5:超 budget 时摘要兜底
        memory_store=context.memory_store,                  # 步6:memory 分层注入
        # 压缩阈值/召回 top_k 走 context.yaml(缺省回落 ContextBuilder 默认);
        # context_budget 不用 context.yaml 的,用 config.context_budget(agent.yaml),避免两个源打架。
        **{k: v for k, v in build_context_builder_params().items() if k != "context_budget"},
    )

    while state.should_continue():
        step = state.new_step()
        _runtime_state.current_step_id.set(step.index)   # before_mutation 回调读它做 track_edit 的 step_id
        sink.emit(StepStart(step_index=step.index))
        step.deadline = time.perf_counter() + config.step_timeout

        try:
            model_request = ModelRequest(
                messages=(await builder.build(state)).messages,
                tools=tools if context.config.enable_tools else [],
                model=context.config.model,
                temperature=context.config.temperature,
                max_tokens=context.config.max_tokens,
            )
            step.model_request = model_request
            # step_timeout 作用于 LLM 调用(对齐 config"每轮 Agent 循环超时"):挂起的流不再永久阻塞。
            # asyncio.wait_for 超时抛 TimeoutError(无 status_code)-> classify_error 判可重试 -> 重试到阈值后 fail。
            # 注:这是总时长上限;极长生成(>step_timeout)需调大 config.step_timeout。
            model_response = await asyncio.wait_for(
                context.model_adapter.stream_llm(model_request, sink),
                timeout=config.step_timeout,
            )
            step.model_response = model_response

            # 本轮 token 累计(对齐 CC QueryEngine.totalUsage:每条 assistant 消息 usage 累加,
            # RunEnd 事件带整轮聚合;子 agent 有独立 state,不混入本 state)
            _u = getattr(model_response, "usage", None)
            if _u is not None:
                state.token_input += getattr(_u, "input_tokens", 0) or 0
                state.token_output += getattr(_u, "output_tokens", 0) or 0
                state.token_total += getattr(_u, "total_tokens", 0) or 0
                state.token_cached += getattr(_u, "cached_tokens", 0) or 0

            # 阶段8: on_output Guardrail(PII 脱敏)在落盘前--否则 transcript 先存原始 PII,内存才脱敏,
            # 脱敏被落盘击败(#12)。对所有回复都过(工具轮 text 通常为空,无副作用;脱敏进 messages+final)。
            if context.guardrail_runner is not None:
                _final_text = getattr(model_response, "text", None) or ""
                _gr = context.guardrail_runner.run("on_output", _final_text, context)
                if _gr.action == "sanitize" and _gr.sanitized is not None:
                    model_response.text = _gr.sanitized

            # 源头发完整 assistant 消息(对齐 CC `assistant`;web 契约,delta 只在 CLI 打字机)
            _emit_assistant_message(sink, state, model_response, step)

            # durability-first：先落盘（decide 前，FINISH/tool_call 两路都保住付费 LLM 回复;此处已脱敏）
            if persister:
                persister.log_assistant(model_response)

            action = decide(model_response)
            if action == Action.FINISH:
                # final 也进 messages 作历史（推翻 Decision 3：多轮对话需要上一轮最终回复作上下文，
                # 否则下一轮 model 看不到、重复回答）。final_response 仍设，给 _emit_run_end 取 final_text。
                state.messages = context.model_adapter.append_assistant(state.messages, model_response)
                if subtask:
                    # plan_execute 子任务:只设结果,不转终态(保持 running,让外层继续下一步)
                    state.final_response = model_response
                else:
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
            subagent_tasks: list = []   # 前台子 agent 挂 task 并行跑,循环后统一收(待办 D)

            def _absorb(r):
                """吸一条 tool result 进状态/落盘/发事件(非 subagent 与前台 subagent 共用)。"""
                # HITL(阶段0 Phase A):权限拒绝在 execute_many 内已回填 GuardrailBlocked ToolResult,
                # 走正常 tool_result 回灌(模型下轮看到"未获确认"换方法)。
                _emit_tool_result_message(sink, state, r)   # 源头发完整工具结果(web 契约)
                if persister:
                    persister.log_tool_result(r)
                state.messages = context.model_adapter.append_tool_result(state.messages, r)
                step.tool_results.append(r)      # 对称：live 也填 step.tool_results（与 replay 一致）
                state.tool_history.append(ToolHistoryEntry(
                    call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
                    error_type=r.error.get("type") if r.error else None))
                tool_results.append(r)

            async for r in context.tool_executor.execute_many(
                model_response.tool_calls, timeout=config.step_timeout, sink=sink
            ): 
                # Task 工具:拦截 subagent 请求(handler 同步跑不了 async agent.run),
                # 异步跑子 agent 用其结果替换 tool result(对标 NeedsApproval 的拦截模式)
                if r.ok and isinstance(r.data, dict) and r.data.get("__subagent__"):
                    if r.data.get("background"):
                        # 后台:fire-and-forget,返回快,inline 吸收
                        _absorb(await _run_subagent(r, context, persister))
                    else:
                        # 前台:不 inline await,挂 task 并行跑——多个前台子 agent 不再串行
                        # 冻住主循环(待办 D);结果在循环后按完成序统一收,保留流式 ToolResultMessage
                        subagent_tasks.append(
                            (r.call_id, asyncio.create_task(_run_subagent(r, context, persister))))
                    continue
                _absorb(r)

            # 前台子 agent 并行收尾(都挂完再收,一轮拿齐全部结果)
            for _call_id, task in subagent_tasks:
                _absorb(await task)

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
                    _soft_stop = SOFT_STOP_HINT.format(step=step.index, tool=tool_results[0].tool_name)
                    state.messages.append(Message(role="user", content=_soft_stop))
                    if persister:
                        persister.log_user(_soft_stop)   # durability-first:合成 user 消息也落盘,resume 不丢
                    loop_detector.reset()

            # 版本链条:本轮工具执行后封口 snapshot(对标 CC makeSnapshot,每轮末)
            _fh = _runtime_state.file_history.get()
            if _fh:
                _fh.make_snapshot(step.index)
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
            _err_hint = (f"[系统提示] 上一步执行失败：{error['type']}: {error['message']}。"
                         f"请根据错误信息调整下一步，或直接给出最终答案。")
            state.messages.append(Message(role="user", content=_err_hint))
            if persister:
                persister.log_user(_err_hint)
            # 可重试且未超阈值：继续下一轮（StepEnd 已发）

    if not state.is_terminal():
        if subtask:
            # plan_execute 子任务超 max_steps:不转终态,回填提示让外层 plan_execute 继续下一步
            _subtask_hint = f"[子任务超过 max_steps={state.max_steps},强制结束当前子任务]"
            state.messages.append(Message(role="user", content=_subtask_hint))
            if persister:
                persister.log_user(_subtask_hint)
            state.final_response = None
        else:
            state.exceed_max_steps()
    return state


async def _run_subagent(request, context: RuntimeContext, persister=None) -> ToolResult:
    """跑一个子 agent 处理 Task 工具的子任务,返回其最终回答作为 ToolResult(对标 CC Task 工具)。

    handler 同步跑不了 async agent.run,故 Task 工具 handler 只返回请求标记,_run_steps 拦截后
    调本函数异步跑子 agent。复用 multiagent.Agent.run(克隆 context + agent_id tracing);
    子 agent fresh state(不继承父 messages,聚焦子任务),tools=全允许(除 handoff,可嵌套 Task)。
    background=True(且 notify_queue 可用):fire-and-forget,立即返回"已派出",子 agent 完成后
    经 notify_queue -> [task-notification] 下轮注入(主 agent 不阻塞,继续做别的)。默认前台阻塞。
    """
    from .multiagent.agent import Agent, subagent_result_text   # 运行期延迟 import:打破模块级循环
    prompt = request.data["prompt"]
    background = request.data.get("background", False)
    # fresh runtime(空 state)-> 子 agent 不继承父 messages,只看自己的 prompt(对标 CC 子 agent 隔离)。
    # 子 agent 事件不打印由 StreamingPrinter 过滤(_runtime_state.agent_id 非 None 即跳过),sink 链路保留:
    # 子 agent span 照常进 tracer/主 trace(带 agent_id),web SSE 也能收到(待办 E 前端有序渲染)。
    fresh_runtime = replace(context, state=AgentState())
    sub_agent = Agent(role="subagent", tools=[], config=context.config, runtime=fresh_runtime)

    if background and context.notify_queue is not None:
        # 后台:fire-and-forget,主 agent 立即继续做别的;子 agent 完成后 notify_queue.put
        # -> run_agent_loop 排干 -> 下轮 [task-notification] 注入(对标 CC Task background)
        from .multiagent.background import launch_background_subagent
        launch_background_subagent(sub_agent, prompt, context.notify_queue)
        return ToolResult(call_id=request.call_id, tool_name="task", ok=True,
                          data={"description": request.data.get("description", ""), "background": True},
                          text="子 agent 已后台派出,完成时会以 [task-notification] 通知主 agent(主 agent 可继续做别的)。",
                          meta=request.meta)

    # 前台(默认):阻塞等子 agent 跑完,结果作为 tool result 当场返回。
    # 若 persister 可用,子 agent 事件带 agent_id="subagent" 落主 transcript(web 可展示子 agent 流)。
    sub_persister = None
    if persister is not None:
        persister.agent_id = "subagent"   # 前台 inline 无并发,可直接改;finally 恢复
        sub_persister = persister
    try:
        sub_state = await sub_agent.run(prompt, persister=sub_persister)
    finally:
        if persister is not None:
            persister.agent_id = None
    # 有 final_response 用其文本;撞 max_steps/异常则回填失败原因,主 agent 读了自行兜底(不再拿空结果卡住)
    text = subagent_result_text(sub_state)
    return ToolResult(call_id=request.call_id, tool_name="task", ok=True,
                      data={"description": request.data.get("description", ""), "result": text},
                      text=text, meta=request.meta)


async def _run_turn(user_input: str, state: AgentState, context: RuntimeContext, persister):
    """单轮体（agentloop 与 REPL 复用）：初始化 messages + log_user + _run_steps。
    不发 RunEnd、不收尾 persister——收尾由调用方负责（agentloop 走 _end_run；REPL 走 session 级收尾）。"""
    config = context.config
    # 1. 初始化对话消息：首轮(system+user)；续轮(只 append user，保留跨轮上下文)
    #    判据：state.messages 是否为空——空=首轮，非空=续轮(已有跨轮历史)
    if not state.messages:
        prompt = build_system_prompt(config)   # 静态核心 + 会话级动态段(对齐 cc getSystemPrompt)
        if prompt:
            state.messages.append(Message(role="system", content=prompt))
    # 阶段8: on_input Guardrail(prompt 注入检测),block 则不进 messages
    if context.guardrail_runner is not None:
        gr = context.guardrail_runner.run("on_input", user_input, context)
        if gr.action == "block":
            state.fail({"type": "GuardrailBlocked", "message": f"输入被拦截:{gr.reason}"})
            return state
    state.messages.append(Message(role="user", content=user_input))
    if persister:
        persister.log_user(user_input)     # durability-first：先落盘再改内存
    # 2. 按 mode 分流(阶段7):react=纯 agentic(默认);plan_execute=先规划再执行;workflow=固定 DAG(commit5)
    mode = config.mode
    if mode == "plan_execute":
        return await _run_plan_execute(user_input, state, context, persister)
    if mode == "workflow":
        return await _run_workflow(state, context, persister)
    return await _run_steps(state, context, persister)


async def _run_plan_execute(user_input: str, state: AgentState, context: RuntimeContext, persister):
    """Plan-and-Execute 模式(阶段7):Planner 产 Plan -> 逐步 _run_steps(subtask=True) -> Critic 防漂移。
    messages 已由 _run_turn 初始化(system+user)。Plan 不进 messages(外置防压缩吞,靠 ContextBuilder 注入当前 step)。
    对齐 stage7-plan §3.3 subtask 轻解法:共享 state,FINISH 不 complete,steps 连续累积。"""
    config = context.config
    planner = Planner(context.model_adapter)
    plan = await planner.make_plan(user_input, context.registry)

    for step_idx, plan_step in enumerate(plan.steps):
        plan_step.status = "in_progress"
        plan.status = "executing"
        state.meta["current_plan_step"] = plan_step.content  # ContextBuilder 读它注入"聚焦当前子任务"
        state.step_index = 0  # 重置:每个 plan step 独占 max_steps 预算,不累加
        await _run_steps(state, context, persister, subtask=True)  # FINISH 不 complete,保持 running
        result = getattr(state.final_response, "text", "") if state.final_response else ""
        plan_step.status = "completed"
        plan_step.result = result
        # 子任务结果作为 observation 回灌(对齐 CC:子 agent 结果 -> parent messages)
        _obs = f"[plan step 完成:{plan_step.content}]\n结果:{result}"
        state.messages.append(Message(role="user", content=_obs))
        if persister:
            persister.log_user(_obs)
        # 防漂移:每 replan_every 步调 Critic 评估计划
        if config.critic_enabled and step_idx % config.replan_every == config.replan_every - 1:
            critique = await Critic(context.model_adapter).evaluate_plan(plan, state)
            if critique.needs_replan:
                plan = await planner.make_plan(user_input, context.registry, prior=plan)
                plan.status = "replanned"

    # 收尾:Critic 验收(可选);不通过也 complete(避免无限 replan,仅记录)
    if config.critic_enabled and state.final_response is not None:
        await Critic(context.model_adapter).evaluate_result(
            user_input, getattr(state.final_response, "text", "") or "")
    state.complete(state.final_response)  # state 仍 running(subtask 未转终态),合法转 completed
    return state


async def _run_workflow(state: AgentState, context: RuntimeContext, persister):
    """Workflow 模式(阶段7):固定 tool_call DAG,LLM 不参与决策,直接 execute_many 按拓扑序执行。
    复用阶段2 _dag_execute(depends_on)。Plan 从 state.meta['workflow_plan'] 读(list[ToolCall])。
    对齐 stage7-plan §3.6:react=LLM 每步决策;plan_execute=LLM 产 Plan+逐步执行;workflow=固定 DAG,LLM 不决策。"""
    config = context.config
    sink = context.sink
    calls = state.meta.get("workflow_plan", [])
    if state.status == "created":
        state.transition("running")
    if not calls:
        state.complete(None)
        return state
    state.transition("waiting_tool")
    async for r in context.tool_executor.execute_many(calls, timeout=config.step_timeout, sink=sink):
        _emit_tool_result_message(sink, state, r)   # 源头发完整工具结果(web 契约)
        if persister:
            persister.log_tool_result(r)
        state.messages = context.model_adapter.append_tool_result(state.messages, r)
        state.tool_history.append(ToolHistoryEntry(
            call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
            error_type=r.error.get("type") if r.error else None))
    state.transition("running")
    state.complete(None)  # workflow 无最终 LLM 回答(进阶可加 LLM 总结);complete(None) 收尾
    return state


async def _execute_pending(state: AgentState, context: RuntimeContext, persister):
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
    async for r in context.tool_executor.execute_many(pending, timeout=config.step_timeout, sink=sink):
        _emit_tool_result_message(sink, state, r)   # 源头发完整工具结果(web 契约)
        if persister:
            persister.log_tool_result(r)
        state.messages = context.model_adapter.append_tool_result(state.messages, r)
        step.tool_results.append(r)
        state.tool_history.append(ToolHistoryEntry(
            call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
            error_type=r.error.get("type") if r.error else None))
    state.transition("running")
