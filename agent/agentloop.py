import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from .config.loader import exit_words

from .config.config import AgentConfig
from .core.state import AgentState
from .core.workspace import Workspace

from .adapters.base import BaseModelAdapter
from .runtime import RuntimeContext
from .tools.registry import ToolExecutor, ToolRegistry
from .streaming.events import RunStart
from .persist.persister import Persister
from .utils.fileHistory import FileHistory
from .persist.paths import run_dir
from .tools import _runtime_state

# loop 机制(主循环/模式/子 agent/发事件)已拆到 runner,本文件只留编排 + REPL + 持久化收尾。
# re-export 兼容旧导入(tests 等从 agent.agentloop 拿 _run_turn/_run_subagent 等)。
from .runner import (
    _run_steps, _run_subagent, _run_turn, _run_plan_execute, _run_workflow,
    _emit_assistant_message, _emit_tool_result_message, _emit_run_end, _execute_pending,
)


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


def _end_run(state: AgentState, sink, persister, event_store=None):
    """单次调用收尾：发 RunEnd + log_run_end + close（agentloop / continue_loop 复用）。
    event_store(可选):前端事件流落盘 sink,与 persister 同生命周期关闭。"""
    _emit_run_end(state, sink)
    if persister:
        persister.log_run_end(state.status, state.error)
        persister.close()
    if event_store is not None:
        event_store.close()

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


def _rate(c: int, i: int) -> str:
    """缓存命中率 cached/input,无 input 返 '-'。"""
    return f"{round(c * 100 / i)}%" if i else "-"
async def continue_loop(state: AgentState, context: RuntimeContext) -> AgentState:
    """resume 续跑：state.messages 已由 resume() 重建，跳过初始化。
    先执行 pending（崩在工具执行中），再进主循环。Persister 以 append 模式复用同一 transcript。"""
    sink = context.sink
    persister = Persister(state.run_id) if context.persist else None
    # 事件流落盘:resume 续跑也挂 EventStore(append 复用同一 events.jsonl)
    event_store = None
    if context.persist:
        from .streaming.sink import CompositeSink
        from .streaming.event_store import EventStore
        event_store = EventStore(state.run_id)
        sink = CompositeSink(sink, event_store)
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
    _end_run(state, sink, persister, event_store=event_store)
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
    # 事件流落盘:persist 时挂 EventStore(web 契约事件 -> events.jsonl),与 transcript 同生命周期
    event_store = None
    if context.persist:
        from .streaming.event_store import EventStore
        event_store = EventStore(state.run_id)
        context.sink = CompositeSink(context.sink, event_store)
    sink = context.sink
    persister = Persister(state.run_id) if context.persist else None
    if context.persist:
        _write_run_start_meta(state.run_id, config.model, config.system_prompt)  # 在途 run 立即可见(问题1)
    _init_file_history(state.run_id, context.persist)   # 版本链条:按 run_id 初始化 file_history
    _runtime_state.model_adapter.set(context.model_adapter)   # 步3 WebFetch 用
    _runtime_state.workspace.set(context.workspace)  # 阶段8:路径权限(None=退回 Path.resolve)

    sink.emit(RunStart(run_id=state.run_id))
    state = await _run_turn(user_input, state, context, persister)
    _end_run(state, sink, persister, event_store=event_store)
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
    # 会话级单 run_id（对齐 CC）：整个 REPL session 共用一个 transcript/events，跨轮 append；
    # 退出时才写 run_end。崩在中途无 run_end -> resume 按最后状态续跑（durability-first 的保证）。
    # 会话机制(run_id/messages/persister/tracer/event_store/notify_queue/turn_lock + turn 组装)
    # 全在 core Session;本函数只留"输入循环 + 控制台渲染"(前端差异留在前端)。
    from .session import Session
    session_run_id = str(uuid.uuid4())
    session = Session.create(
        run_id=session_run_id,
        registry=registry, model_adapter=model_adapter, tool_executor=tool_executor,
        config=config, guardrail_runner=tool_executor.guardrail_runner,  # 阶段8
        memory_store=memory_store,  # 步6:传给 builder 分层注入
        workspace=Workspace(root=Path(config.workspace_root) if config.workspace_root else Path.cwd()),  # 工作区间(config.workspace_root / AGENT_WORKSPACE)
        file_history=FileHistory(run_dir(session_run_id) / "file-history"),  # 版本链条(同旧 _init_file_history)
    )
    _write_run_start_meta(session_run_id, config.model, config.system_prompt)  # 在途 run 立即可见(问题1)
    last_state = None

    async def _do_turn(user_input: str) -> AgentState:
        """跑一轮(会话机制全在 session.run_turn:组装/同步/RunEnd/run_meta)。输入与通知复用。"""
        nonlocal last_state
        state = await session.run_turn(user_input, printer)
        # 每轮 token 打印(REPL 专属;本轮用 state 累计,累计用 MetricsCollector 跨所有 span 含子 agent)
        from .tracing.metrics import MetricsCollector
        rep = MetricsCollector().collect(session.tracer.trace)
        print(f"  [本轮 in:{state.token_input} out:{state.token_output} "
              f"cache:{state.token_cached}({_rate(state.token_cached, state.token_input)}) / "
              f"累计 in:{rep.token_input} out:{rep.token_output} cache:{rep.token_cached}({_rate(rep.token_cached, rep.token_input)})]")
        last_state = state
        return state

    input_task: Optional[asyncio.Task] = None   # 跨轮复用,不 cancel(线程池 input 无法取消)
    input_prompt_shown = False   # 当前输出行是否以未换行的 "User: " 提示结尾;任何后续输出前需补换行

    async def _handle_notification(role: str, text: str, status: str) -> None:
        """注入一条后台 subagent 完成通知,让主 agent 读子 agent 结果并整合。

        通知必须以消息形式注入(模型要读到子 agent 结果,对齐 CC messageQueueManager);
        这里在 turn 前打印系统提示行,与真实用户输入区分。status 带结构化成败
        (completed/failed/stopped,对齐 CC 通知 <status>),主 agent 一眼知道子 agent 结果。
        处理完若用户还没输入(还在等 prompt),重打一个 "User: " 提示——原 prompt 被
        流式输出顶走,不提示的话用户不知现在能输入,会傻等或按回车试探
        (产生空 user 消息,主 agent 还对着空消息回复一轮)。
        """
        nonlocal input_prompt_shown
        if input_prompt_shown:
            print()   # 上一行是未换行的 "User: ",先补换行,避免 [后台任务]/流式输出打同一行
            input_prompt_shown = False
        print(f"  [后台任务] {role} 完成(status={status}),已注入主 agent 处理…")
        await _do_turn(session.notification_input(role, text, status))
        if input_task is not None and not input_task.done():
            print("User: ", end="", flush=True)   # 重打 prompt(无换行),标记行未结束
            input_prompt_shown = True

    try:
        while True:
            # 1. 排干后台 subagent notification(作为 user 消息注入,对标 CC messageQueueManager)。
            #    notification 不读 input,直接进 turn 让 agent 处理后台 subagent 的结果。
            while not session.notify_queue.empty():
                role, text, status = session.notify_queue.get_nowait()
                await _handle_notification(role, text, status)
            # 2. 竞速:用户输入 vs 新通知(对标 CC 命令队列非空即自动处理)。
            #    通知到达即自动触发新 turn(不用按回车);input_task 跨轮复用绝不 cancel
            #    (线程池 input() 无法取消,重复 create 会并发读 stdin 抢输入);
            #    break 只发生在 input_task done(用户输入退出词),此时无 pending 输入线程。
            if input_task is None:
                input_task = asyncio.create_task(_ainput("User: "))
                input_prompt_shown = True   # prompt 显示中(阻塞等输入),行未结束
            notify_task = asyncio.create_task(session.notify_queue.get())
            done, _ = await asyncio.wait(
                {input_task, notify_task}, return_when=asyncio.FIRST_COMPLETED)
            if notify_task not in done:
                notify_task.cancel()          # 输入先到:取消通知等待
            if notify_task in done:
                role, text, status = notify_task.result()
                await _handle_notification(role, text, status)
            if input_task in done:
                user_input = input_task.result()
                input_task = None             # 重建下一轮输入
                input_prompt_shown = False    # 用户按了回车,"User: " 行已结束
                if user_input.lower() in set(exit_words()):   # 退出词走 agent.yaml(缺省 exit/quit)
                    print("Exiting agent loop.")
                    break
                if user_input.strip():        # 空输入(只按回车)忽略:回等待,不产生空 user 消息
                    await _do_turn(user_input)
        # session 正常退出：写 run_end（用最后一轮 status）；崩在 finally 前则不写 -> resume 续跑
        if last_state is not None:
            session.close(status=last_state.status, error=last_state.error)
        # 阶段9:session 退出聚合 Metrics(run_meta 已每轮增量落盘,这里只打印)
        from .tracing.metrics import MetricsCollector
        rep = MetricsCollector().collect(session.tracer.trace)
        print(f"[trace] session {rep.status} steps={rep.step_count} tools={rep.tool_count} "
              f"tokens={rep.token_total} tool_ok={rep.tool_success_rate:.0%}", file=sys.stderr)
    finally:
        session.close()   # 幂等:正常退出已 close,异常路径兜底

def main():
    # 组合根(agent/bootstrap.py):共享运行时依赖(adapter/config/guardrail/tool_executor/
    # memory/tools 注册)唯一装配点,CLI 与 web server 共用。
    from .bootstrap import build_runtime
    try:
        rt = build_runtime()   # confirmer 缺省 = cli_confirmer(CLI)
    except RuntimeError as e:
        raise SystemExit(str(e))
    import asyncio
    asyncio.run(run_agent_loop(rt.registry, rt.model_adapter, rt.tool_executor,
                               config=rt.config, memory_store=rt.memory_store))
if __name__ == "__main__":
    main()