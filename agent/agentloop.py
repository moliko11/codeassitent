from dataclasses import dataclass, field
import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .core.errors import classify_error

from .control.actions import Action, decide

from .prompts import SOFT_STOP_HINT, build_system_prompt

from .control.loop_detector import LoopDetector
from .control.planner import Planner
from .control.critic import Critic
from .config.loader import (
    build_agent_config, build_context_builder_params, build_guardrail_runner,
    build_memory_params, build_tool_executor_params, exit_words, get_section,
)

from .config.config import AgentConfig
from .config.provider import load_provider_config, make_adapter
from .core.state import AgentState, ToolHistoryEntry
from .core.workspace import Workspace

from .adapters.base import BaseModelAdapter
from .core.models import ModelRequest
from .core.messages import Message
from .runtime import RuntimeContext
from .tools.registry import ToolExecutor, ToolRegistry
from .tools.defs import ToolResult
from .streaming.events import RunStart, StepStart, StepEnd, RunEnd
# agentloop.py -- import 区加一行
from .persist.persister import Persister
from .context.builder import ContextBuilder
from .context.auto_compact import make_summarizer
from .utils.fileHistory import FileHistory
from .persist.paths import run_dir
from .tools import _runtime_state


def _track_edit_callback(call):
    """ToolExecutor.before_mutation 回调:Edit/Write 写盘前调 file_history.track_edit 备份。

    无 file_path 的工具(如 Bash)跳过--命令副作用不可追踪(对标 CC 边界,靠 git)。
    file_history / current_step_id 由 _init_file_history / _run_steps 注入 _runtime_state。
    """
    fh = _runtime_state.file_history.get()
    if fh is None:
        return
    file_path = call.arguments.get("file_path")
    if not file_path:
        return
    # 路径解析与 edit/write 一致(ws.resolve):否则 backup key 走 cwd-based Path.resolve,
    # 与实际改的 workspace-based 文件不一致,workspace≠cwd 时 rewind 回滚到错文件(#2)。
    ws = _runtime_state.workspace.get()
    resolved = str(ws.resolve(file_path)) if ws else str(Path(file_path).resolve())
    fh.track_edit(resolved, _runtime_state.current_step_id.get())


def _init_file_history(run_id: str, persist: bool):
    """按 run_id 初始化 file_history(备份根:persist/runs/<run_id>/file-history/)。
    persist=False 不初始化(测试入口/非持久 run);测试可手动设 _runtime_state.file_history。"""
    if not persist:
        return
    _runtime_state.reset()
    _runtime_state.file_history.set(FileHistory(run_dir(run_id) / "file-history"))


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
    if allowed:
        # 白名单:只给模型看 allowed_tools 内的工具(权限隔离,题16;commit 10)
        tools = [t.tool_spec for t in all_tools if t.tool_spec.name in allowed]
    else:
        # 空=全允许(单 agent 默认);但 handoff 是特权工具(orchestrator 委派用),不自动放开,
        # 防子 agent 递归调子 agent(子 agent 无权再 handoff)。单 agent 不注册 handoff,此处无影响。
        tools = [t.tool_spec for t in all_tools if t.tool_spec.name != "handoff"]

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

            # 阶段8: on_output Guardrail(PII 脱敏)在落盘前--否则 transcript 先存原始 PII,内存才脱敏,
            # 脱敏被落盘击败(#12)。对所有回复都过(工具轮 text 通常为空,无副作用;脱敏进 messages+final)。
            if context.guardrail_runner is not None:
                _final_text = getattr(model_response, "text", None) or ""
                _gr = context.guardrail_runner.run("on_output", _final_text, context)
                if _gr.action == "sanitize" and _gr.sanitized is not None:
                    model_response.text = _gr.sanitized

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
            async for r in context.tool_executor.execute_many(
                model_response.tool_calls, timeout=config.step_timeout, sink=sink
            ):
                # Task 工具:拦截 subagent 请求(handler 同步跑不了 async agent.run),
                # 异步跑子 agent 用其结果替换 tool result(对标 NeedsApproval 的拦截模式)
                if r.ok and isinstance(r.data, dict) and r.data.get("__subagent__"):
                    r = await _run_subagent(r, context, persister)
                # HITL(阶段0 Phase A):权限拒绝在 execute_many 内已回填 GuardrailBlocked ToolResult,
                # 走正常 tool_result 回灌(模型下轮看到"未获确认"换方法)。waiting_approval 态留给
                # Phase B 持久化挂起(mobile/云,resume 续跑)。
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
    from dataclasses import replace
    from .multiagent.agent import Agent
    prompt = request.data["prompt"]
    background = request.data.get("background", False)
    # fresh runtime(空 state)-> 子 agent 不继承父 messages,只看自己的 prompt(对标 CC 子 agent 隔离)
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
    text = getattr(sub_state.final_response, "text", "") if sub_state.final_response else ""
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
        if persister:
            persister.log_tool_result(r)
        state.messages = context.model_adapter.append_tool_result(state.messages, r)
        state.tool_history.append(ToolHistoryEntry(
            call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
            error_type=r.error.get("type") if r.error else None))
    state.transition("running")
    state.complete(None)  # workflow 无最终 LLM 回答(进阶可加 LLM 总结);complete(None) 收尾
    return state


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

def _first_user_title(messages, limit: int = 30) -> str:
    """从 messages 取首条真实 user 消息作会话 title(Phase 1 §1.1)。

    跳过系统注入的合成 user 消息([plan step]/[task-notification]/[子任务]/[系统提示] 前缀);
    content 可能是 dict(工具轮 user 回灌)或非 str,跳过;截断到 limit(超长加 …)。"""
    for m in messages:
        if getattr(m, "role", None) != "user":
            continue
        text = getattr(m, "content", "")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text or text.startswith(("[plan step", "[task-notification", "[子任务", "[系统提示")):
            continue
        return text if len(text) <= limit else text[:limit] + "…"
    return ""


def _write_run_meta(state: AgentState, report, model: str, title: str | None = None):
    """RunEnd 落盘 run_meta.json 侧车(监控 M1):列表 O(1) 读摘要,不 load trace(坑3)。
    崩了没 RunEnd -> 不调本函数 -> 无侧车 -> list_runs 退化扫 transcript(坑2)。
    - status 用 state(真相),不用 report.status:REPL 的 trace 无 run span(RunStart/End
      直发 printer 绕过 tracer),report.status 会是 'unknown'。
    - started_at 用墙钟:state.created_at 是 perf_counter(非墙钟),by_day 需真日期;
      duration 来自 perf_counter 差(准),用 ended_at - duration 回推出墙钟 start。
    - token 来自 report(step span attrs["usage"] 之和,坑1:LLM 返回的精确值,非估算)。
    - system_prompt 取 state.messages 里实际注入的 system 消息(首轮 append 的;动态组装
      build_system_prompt 后此处即动态版),保证监控展示 = 模型实际收到的。
    - title:Phase 1 §1.1;显式传入(用户重命名过)用之,否则从首条 user 消息推导。"""
    import json
    from .persist.paths import run_meta_path
    # 取实际注入的 system 提示词(静态 config.system_prompt 或动态 build_system_prompt 结果)
    sys_prompt = ""
    for m in state.messages:
        if getattr(m, "role", None) == "system":
            sys_prompt = getattr(m, "content", "") or ""
            break
    ended_at = time.time()
    meta = {
        "run_id": state.run_id,
        "title": title if title is not None else _first_user_title(state.messages),
        "status": state.status,
        "started_at": ended_at - (report.duration_ms or 0) / 1000.0,
        "ended_at": ended_at,
        "duration_ms": report.duration_ms,
        "token_input": report.token_input,
        "token_output": report.token_output,
        "token_total": report.token_total,
        "token_cached": report.token_cached,         # 缓存命中 token(命中率=cached/input,为 cost §8 铺路)
        "step_count": report.step_count,
        "tool_count": report.tool_count,
        "tool_success_rate": report.tool_success_rate,
        "model": model,                             # 给后续 cost 用(§8 TODO)
        "system_prompt": sys_prompt,                # 实际注入的(静态/动态都准),详情页分层展示
    }
    run_meta_path(state.run_id).write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _write_run_start_meta(run_id: str, model: str, system_prompt: str):
    """run 开始就写最小 run_meta.json(status=running + 真实墙钟 started_at),让 list_runs 立即展示
    在途 run(不等第一轮完成)。_write_run_meta 轮末覆盖更新真实 token/duration/status。"""
    import json
    from .persist.paths import run_meta_path
    meta = {
        "run_id": run_id,
        "status": "running",
        "started_at": time.time(),   # 墙钟(开始时刻);_write_run_meta 轮末用 ended_at-duration 回推覆盖
        "ended_at": None,
        "duration_ms": 0.0,
        "token_input": 0, "token_output": 0, "token_total": 0, "token_cached": 0,
        "step_count": 0, "tool_count": 0, "tool_success_rate": 0.0,
        "model": model,
        "system_prompt": system_prompt,
    }
    run_meta_path(run_id).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def _sum_step_usage(spans) -> tuple[int, int, int, int]:
    """sum step span 的 usage,返回 (input, output, total, cached)。total=0 用 input+output 兜底(坑4)。
    REPL 每轮末尾打印 token 用:本轮 = 新增 span,累计 = 全部 span。"""
    ti = to = tt = tc = 0
    for s in spans:
        if s.type != "step":
            continue
        u = s.attrs.get("usage")
        if not u:
            continue
        i = u.get("input_tokens", 0) or 0
        o = u.get("output_tokens", 0) or 0
        t = u.get("total_tokens", 0) or 0
        ti += i
        to += o
        tt += t if t > 0 else i + o
        tc += u.get("cached_tokens", 0) or 0
    return ti, to, tt, tc


def _rate(c: int, i: int) -> str:
    """缓存命中率 cached/input,无 input 返 '-'。"""
    return f"{round(c * 100 / i)}%" if i else "-"

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
        if persister:
            persister.log_tool_result(r)
        state.messages = context.model_adapter.append_tool_result(state.messages, r)
        step.tool_results.append(r)
        state.tool_history.append(ToolHistoryEntry(
            call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
            error_type=r.error.get("type") if r.error else None))
    state.transition("running")


async def continue_loop(state: AgentState, context: RuntimeContext) -> AgentState:
    """resume 续跑：state.messages 已由 resume() 重建，跳过初始化。
    先执行 pending（崩在工具执行中），再进主循环。Persister 以 append 模式复用同一 transcript。"""
    sink = context.sink
    persister = Persister(state.run_id) if context.persist else None
    # 续跑也须初始化 _runtime_state(与 agentloop/run_agent_loop 入口对齐):
    # 否则 model_adapter/workspace/file_history 全 None -> WebFetch 坏、edit/write 跳权限校验、
    # 无备份/rewind、read_file_state 空 -> Edit 报"先读后改"(阶段5 验收 resume 涉文件任务必崩)。
    _init_file_history(state.run_id, context.persist)
    _runtime_state.model_adapter.set(context.model_adapter)
    _runtime_state.workspace.set(context.workspace)
    sink.emit(RunStart(run_id=state.run_id))
    # 续跑重置步数计数：max_steps 是单轮上限，重放出的历史 steps 不该吃掉续跑预算。
    # steps 保留为历史轨迹（审计/重放），step_index 仅控制"还能跑几步"。
    state.step_index = 0
    await _execute_pending(state, context, persister)
    state = await _run_steps(state, context, persister)
    _end_run(state, sink, persister)
    return state

async def agentloop(user_input: str, context: RuntimeContext) -> AgentState:
    """运行 Agent 主循环（流式版 + 可选消息级落盘）。单次调用自洽：
    自建 Persister、结束写 run_end + close。REPL 多轮复用走 _run_turn，不经过这里。"""
    config = context.config or AgentConfig()
    state = context.state or AgentState(max_steps=config.max_steps)
    # 阶段9:挂 Tracer(CompositeSink:原 sink + tracer,零侵入主循环)
    from .streaming.sink import CompositeSink
    from .tracing import Tracer, TraceStore
    tracer = Tracer(state.run_id, store=TraceStore(state.run_id) if context.persist else None)
    context.sink = CompositeSink(context.sink, tracer)
    sink = context.sink
    persister = Persister(state.run_id) if context.persist else None
    if context.persist:
        _write_run_start_meta(state.run_id, config.model, config.system_prompt)  # 在途 run 立即可见(问题1)
    _init_file_history(state.run_id, context.persist)   # 版本链条:按 run_id 初始化 file_history
    _runtime_state.model_adapter.set(context.model_adapter)   # 步3 WebFetch 用
    _runtime_state.workspace.set(context.workspace)  # 阶段8:路径权限(None=退回 Path.resolve)

    sink.emit(RunStart(run_id=state.run_id))
    state = await _run_turn(user_input, state, context, persister)
    _end_run(state, sink, persister)
    # 阶段9:run 结束聚合 Metrics(打印到 stderr)
    from .tracing.metrics import MetricsCollector
    rep = MetricsCollector().collect(tracer.trace)
    print(f"[trace] {rep.status} steps={rep.step_count} tools={rep.tool_count} "
          f"tokens={rep.token_total} tool_ok={rep.tool_success_rate:.0%}", file=sys.stderr)
    # 监控 M1:落盘 run_meta.json 侧车(列表 O(1) 读)。persist=False 不落(测试/非持久 run)。
    if context.persist:
        _write_run_meta(state, rep, config.model)
    return state


async def _ainput(prompt: str) -> str:
    """input 丢线程池,不阻塞事件循环(Step 4 收尾)。

    后台 subagent 是同一事件循环上的 asyncio.Task;同步 input 会霸住 loop 线程,
    后台 subagent 既无法推进、也无法往 notify_queue put。丢进 executor 才能让 loop 继续转。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)


async def run_agent_loop(registry: ToolRegistry,
                 model_adapter: BaseModelAdapter,
                 tool_executor: ToolExecutor, 
                 config: Optional[AgentConfig] = None, memory_store=None,
                 ):
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
    from .streaming.sink import CompositeSink
    from .tracing import Tracer, TraceStore
    tracer = Tracer(session_run_id, store=TraceStore(session_run_id))
    messages: list = []               # 跨轮累积上下文（内存共享 list）
    persister = Persister(session_run_id)
    _write_run_start_meta(session_run_id, config.model, config.system_prompt)  # 在途 run 立即可见(问题1)
    _init_file_history(session_run_id, True)   # 版本链条:REPL 持久化,按 session_run_id 初始化
    _runtime_state.model_adapter.set(model_adapter)   # 步3 WebFetch 用
    _runtime_state.workspace.set(Workspace(root=Path.cwd()))  # 阶段8:REPL 工作空间=cwd
    notify_queue = asyncio.Queue()  # 后台 subagent 完成通知通道(put (role, text);commit 9 注入)
    last_state = None

    async def _do_turn(user_input: str) -> AgentState:
        """跑一轮:新 state + context + _run_turn + messages 同步。REPL 输入与 notification 复用。"""
        nonlocal messages, last_state
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
            sink=CompositeSink(printer, tracer),
            persist=True,
            guardrail_runner=tool_executor.guardrail_runner,  # 阶段8
            memory_store=memory_store,  # 步6:传给 builder 分层注入
            notify_queue=notify_queue,  # commit 9:后台 subagent 通知通道
        )
        # 文本/工具进度已在运行中由 StreamingPrinter 实时流式打印。
        # _run_turn 往 state.messages append user(in-place)；但 append_assistant/tool_result 返回
        # 新 list(copy)，state.messages 会离开共享 messages 对象，故每轮结束用 messages = state.messages
        # 同步（见下），否则下一轮丢失上一轮 assistant + tool_result（bug2）。
        context.sink.emit(RunStart(run_id=session_run_id))   # 走 CompositeSink(printer+tracer),让 tracer 收到 RunStart 建 run span
        spans_before = len(tracer.trace.spans)          # 记本轮前 span 数,差出本轮新增(算本轮 token)
        state = await _run_turn(user_input, state, context, persister)
        _emit_run_end(state, context.sink)   # 走 CompositeSink -> tracer 收 RunEnd 落盘 trace.jsonl(修 REPL 无 trace 的坑)
        # 每轮末尾:聚合 Metrics(会话级累计)+ 打印 token + 增量落盘 run_meta
        # 增量写:每轮结束就落盘(累计),崩在下一轮前也保留到最近完成的轮(用户要求,不依赖 exit)
        from .tracing.metrics import MetricsCollector
        rep = MetricsCollector().collect(tracer.trace)
        turn_in, turn_out, _, turn_cached = _sum_step_usage(tracer.trace.spans[spans_before:])
        print(f"  [本轮 in:{turn_in} out:{turn_out} cache:{turn_cached}({_rate(turn_cached, turn_in)}) / "
              f"累计 in:{rep.token_input} out:{rep.token_output} cache:{rep.token_cached}({_rate(rep.token_cached, rep.token_input)})]")
        _write_run_meta(state, rep, config.model)
        messages = state.messages   # 同步共享 list（append 返回 copy，state.messages 已离开原对象）
        last_state = state
        return state

    try:
        while True:
            # 1. 排干后台 subagent notification(作为 user 消息注入,对标 CC messageQueueManager)。
            #    notification 不读 input,直接进 turn 让 agent 处理后台 subagent 的结果。
            while not notify_queue.empty():
                role, text = notify_queue.get_nowait()
                await _do_turn(f"[task-notification] {role} 完成:\n{text}")
            # 2. 读用户输入(非阻塞:input 丢线程池,不卡事件循环,后台 subagent 可并发 put)。
            #    注:notification 若在 _ainput 期间到达,下一轮迭代顶部排干时处理
            #    (响应性留 TODO:可 race input vs notify_queue.get 提前唤醒)。
            user_input = await _ainput("User: ")
            if user_input.lower() in set(exit_words()):   # 退出词走 agent.yaml(缺省 exit/quit)
                print("Exiting agent loop.")
                break
            await _do_turn(user_input)
        # session 正常退出：写 run_end（用最后一轮 status）；崩在 finally 前则不写 -> resume 续跑
        if last_state is not None:
            persister.log_run_end(last_state.status, last_state.error)
        # 阶段9:session 退出聚合 Metrics(run_meta 已在每轮 _do_turn 增量落盘,这里只打印)
        from .tracing.metrics import MetricsCollector
        rep = MetricsCollector().collect(tracer.trace)
        print(f"[trace] session {rep.status} steps={rep.step_count} tools={rep.tool_count} "
              f"tokens={rep.token_total} tool_ok={rep.tool_success_rate:.0%}", file=sys.stderr)
    finally:
        persister.close()

def main():
    # 用 tools 子包的默认 registry：@tool 装饰器把 getnowtime 注册到了那里
    import agent.tools
    registry = agent.tools.registry
    # 装配全部走 code/config/*.yaml(缺省回落 Python 默认,行为与旧硬编码一致)。
    # provider 默认见 provider.yaml(现 openai_compatible/DeepSeek),AGENT_PROVIDER env 可覆盖。
    pc = load_provider_config()
    if not pc.api_key:
        prefix = "VOLCANO_ENGINE" if pc.provider == "ark" else "DEEPSEEK"
        raise SystemExit(f"未设置 {prefix}_API_KEY，请在 code/.env 配置 {prefix}_API_KEY/BASE_URL/MODEL")
    model_adapter = make_adapter(pc)
    # 用 provider 配置里的 model(DEEPSEEK_MODEL)覆盖 AgentConfig 默认,否则 agentloop 会把
    # config.model 直接发给 API,provider 的 model 形同虚设。
    config = build_agent_config({"model": pc.model})
    # 阶段8: GuardrailRunner + 默认 Guard(guardrails.yaml 控制启用清单;未知 guard 名 fail-fast)
    # 阶段0(Phase A):权限判定在 ToolExecutor.can_use_tool(默认 cli_confirmer),不注册为 guard。
    guardrail_runner = build_guardrail_runner()
    # 可靠性四件套 + 执行参数(reliability.yaml;audit disabled -> audit_logger=None)。
    tool_executor = ToolExecutor(
        registry, before_mutation=_track_edit_callback,
        guardrail_runner=guardrail_runner, config=config,
        **build_tool_executor_params(),
    )

    # 工具超时/截断参数(tools.yaml),给 @tool handler 的 t() 查找用
    from .tools.settings import configure_tools
    configure_tools(get_section("tools"))
    # 步6:创建 memory_store + 注册 save_memory 工具(闭包捕获 store)
    from .memory import MemoryStore
    from .persist.paths import memory_dir
    from .tools.memory_tool import make_save_memory_tool
    from .tools.task_tool import make_task_tool
    memory_store = MemoryStore(memory_dir(), **build_memory_params())
    registry.register(make_save_memory_tool(memory_store))
    registry.register(make_task_tool())  # 阶段10:Task 工具(主 agent 派子 agent,CC 小弟模型)

    import asyncio
    asyncio.run(run_agent_loop(registry, model_adapter, tool_executor, config=config))
if __name__ == "__main__":
    main()