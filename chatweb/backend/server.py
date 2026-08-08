# web/server.py - FastAPI 网关:HTTP/SSE 端点(会话机制在 core Session)
#
# 三层链路的 Python 端(对齐 chat-template-integration §2/§6):
#   Next.js BFF -> 本 server(FastAPI,本地 :8000)-> code/agent 核心(零改动)
#
# 会话机制(run_id/messages/persister/tracer/event_store/notify_queue/turn_lock + run_turn)
# 已上收为 agent.session.Session,CLI REPL / web / desktop 三端共用(SessionState 继承它)。
# 本 server 只做三件事:装配共享运行时依赖一次、往 SSESink 推事件、触发 turn。
#
# 端点:
#   POST /sessions            创建 session(新 run_id,SessionState.create 装配)
#   POST /sessions/:id/turn   多轮:sess.run_turn,SSE 流回(POST + ReadableStream,不用 EventSource)
#   GET  /sessions            list_runs() 喂 sidebar
#   GET  /sessions/:id        read_run_report() 单 run 指标
#
# HITL(阶段0 Phase A):async confirmer + can_use_tool 已落地(hitl-approval-design.md §4)。
# 本 server 注入 web_confirmer(推前端弹窗 + await future),POST /approve/{id} 解 future。
# 覆盖:git 写命令(ASK)+ 高风险工具(high_risk=True)。非 tty fail-closed 的兜底在 confirmer。
import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ---- code/agent 复用(import 一次,模块级共享)----
from agent.bootstrap import build_runtime
from agent.core.state import _ser
from agent.core.workspace import Workspace
from agent.streaming.sse_sink import SSESink
from agent.streaming.events import RunEnd, StreamEvent, is_web_event
from agent.persist.paths import PERSIST_ROOT
from agent.persist.store import list_runs, read_run_report, read_transcript, read_events, set_run_title
from agent.agentloop import _first_user_title
from agent.persist.replay import resume
from agent.prompts import build_system_prompt
from agent.core.messages import Message
from agent.guardrails.confirmer import (
    ApprovalDecision, web_confirmer, set_active_sse_queue, resolve_web_approval,
)

from .session_manager import SessionManager, SessionState, make_file_history
from .file_history_api import router as file_history_router


# ─────────────────── 组合根(模块级共享件)───────────────────
# 共享运行时依赖(adapter/config/guardrail/tool_executor/memory/tools 注册)唯一装配点
# 在 agent/bootstrap.py(CLI main 与 web server 共用);本 server 只注入 web_confirmer 并
# 建自己的 workspace。web server 须在 code/ 下启动(同 REPL,PERSIST_ROOT 相对路径)。
_rt = build_runtime(confirmer=web_confirmer)   # 阶段0(Phase A):HITL 走 web_confirmer(推前端弹窗+await future)
_adapter = _rt.model_adapter
_config = _rt.config
_registry = _rt.registry
_guardrail_runner = _rt.guardrail_runner
_tool_executor = _rt.tool_executor
_memory_store = _rt.memory_store
_workspace = Workspace(root=Path(_config.workspace_root) if _config.workspace_root else Path.cwd())

session_manager = SessionManager()


def ensure_session(run_id: str) -> SessionState | None:
    """session miss 时从 transcript 重建(懒加载,对齐 CC --resume / resume() 全重放)。
    重建 messages(含动态 system)+ 复用同一 transcript(Persister append 续写)+ 新 tracer。
    transcript 不存在 -> None(真 404)。pending(崩在工具执行中)暂不执行,留 TODO。"""
    sess = session_manager.get(run_id)
    if sess:
        return sess
    # miss: transcript 不存在 = 真 404(未知 session)
    if not (PERSIST_ROOT / run_id / "transcript.jsonl").exists():
        return None
    # 全重放重建 state(resume 含 apply_message + _detect_pending;system 从 config 重建)
    state = resume(run_id, _config, _adapter)
    # 替换 system 为动态版(build_system_prompt:核心 + 会话级动态段 env/language/frc 等)
    if state.messages and getattr(state.messages[0], "role", None) == "system":
        state.messages[0] = Message(role="system", content=build_system_prompt(_config))
    # 复用同一 transcript(append 模式续写,不新建 run_id)+ 新 tracer/event_store:
    # SessionState.create 继承 Session.create(内部按 run_id 建 Persister/Tracer/EventStore)
    sess = SessionState.create(
        run_id=run_id, messages=state.messages,
        title=_first_user_title(state.messages),   # Phase 1 §1.1:重建时从历史首条 user 推导
        file_history=make_file_history(run_id),    # Phase 2 §2.5:重建 FileHistory(含 sidecar 恢复)
        registry=_registry, model_adapter=_adapter, tool_executor=_tool_executor,
        config=_config, guardrail_runner=_guardrail_runner,
        memory_store=_memory_store, workspace=_workspace,
    )
    session_manager._sessions[run_id] = sess  # 缓存,warm path 下次直接命中
    _start_session_loop(sess)   # 后台通知消费者(待办 A;resume 的 session 也要能收子 agent 通知)
    return sess


# ─────────────────── 后台通知闭环(待办 A,对齐 CC 命令队列 + processQueueIfReady)───────────────────
# web 没有 REPL 那个"活着的循环"(CLI 靠 run_agent_loop 的 while + asyncio.wait 竞速自动起 turn),
# 所以用一个 session 级消费者 loop 补上:_session_loop 消费 sess.notify_queue(唯一消费者,
# 天然 exactly-once),通知到达 -> 自动起一轮 turn(Session.run_turn 内部持 turn_lock 串行,
# 用户 turn 优先,CC 优先级 next > later)。
# 事件经 per-turn SSESink -> sess.event_queue,前端 long-poll GET /sessions/{id}/events 拉(无持久 SSE)。


async def _run_auto_turn(sess: SessionState, notification: str,
                         role: str = "subagent", status: str = "completed", text: str = ""):
    """自动 turn:合成 [task-notification] user 消息跑一轮(会话机制全在 sess.run_turn:
    发 TaskNotification 事件 + 持锁串行 + 同步 messages + RunEnd + run_meta)。
    单通道:事件直接进 sess.event_queue(常驻 SSE 流 /stream 消费),HITL 审批事件
    也进同一队列(set_active_sse_queue 指向它)——不再 per-turn 队列 + 搬运。"""
    set_active_sse_queue(sess.event_queue)   # HITL 审批事件进 session 事件队列(单通道)
    await sess.run_turn(notification, SSESink(sess.event_queue), notification=(role, text, status))


async def _session_loop(sess: SessionState, run_auto_turn=None):
    """session 级通知消费者(等价 CC processQueueIfReady 的空闲自动处理 + 用户输入优先)。

    只消费 sess.notify_queue(唯一消费者 -> 通知只出队一次,不会和用户 turn 重复注入)。
    通知到达 -> 自动起一轮新 turn(串行交给 Session.run_turn 的 turn_lock;用户 turn 在跑就
    等着,CC 'next' > 'later' 的用户输入优先)。loop 随 session close 取消。
    """
    if run_auto_turn is None:
        run_auto_turn = _run_auto_turn
    try:
        while True:
            role, text, status = await sess.notify_queue.get()
            try:
                await run_auto_turn(
                    sess, f"[task-notification] {role} 完成(status={status}):\n{text}",
                    role=role, status=status, text=text)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass   # 单次自动 turn 失败不杀 loop(状态已 fail,run_meta 照落)
    except asyncio.CancelledError:
        pass


def _start_session_loop(sess: SessionState):
    """在 session 上挂通知消费者 loop(幂等)。须在 running event loop 内调用(create/ensure 都是 async)。"""
    if sess.loop_task is None or sess.loop_task.done():
        sess.loop_task = asyncio.create_task(_session_loop(sess))


def _event_to_dict(ev: StreamEvent) -> dict:
    """事件 -> JSON dict,加 `type` 标签(前端 reducer 按它分发)。用 _ser 跳 raw(同 transcript)。"""
    d = _ser(ev)
    d["type"] = type(ev).__name__
    return d


# 原 _is_web_event 已上收为单点契约 agent.streaming.events.is_web_event
# (web SSE 过滤 与 EventStore 落盘共用同一判定,前端 events.ts 是它的 TS 镜像)。
# 放行:消息级(AssistantMessage/ToolResultMessage)+ RunStart/RunEnd 书签 + ToolStart
# (resume/_workflow 无 LLM step 时给前端建工具卡)+ HITL(ApprovalRequestEvent 不走 sink,直接入队)
# + TaskNotification(后台子 agent 完成通知,前端渲染系统提示行)。
# 吞掉:TextDelta/ThinkingDelta/ToolCall*/ToolEnd/StepStart/StepEnd/MessageEnd(delta 与机制事件,
# tracer/printer 已消费,web 无需)。前端由此拿到自包含的完整事件,不用再累积 delta。


# ─────────────────── FastAPI app ───────────────────

app = FastAPI(title="ez-interview agent web")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 静态导出后前端跨源直连(CORS 全开);web/桌面同用
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(file_history_router)   # Phase 2 §2.5:桌面 diff 视图(/sessions/{id}/files*)


class TurnBody(BaseModel):
    input: str


class ApproveBody(BaseModel):
    allow: bool = False
    reason: str = ""


class RenameBody(BaseModel):
    title: str


@app.post("/approve/{request_id}")
async def approve(request_id: str, body: ApproveBody):
    """HITL(阶段0 Phase A):前端弹窗用户点完,POST 回来解 future,让 web_confirmer 的 await 继续。
    allow=True 放行工具执行;False 回填 GuardrailBlocked(模型换方法)。"""
    decision = ApprovalDecision(allow=body.allow, reason=body.reason)
    resolve_web_approval(request_id, decision)
    return {"ok": True}


@app.post("/sessions/{run_id}/rename")
async def rename_session(run_id: str, body: RenameBody):
    """Phase 1 §1.1:重命名会话标题。session 内存态 + run_meta 侧车双写(下次 list_runs/恢复都拿到)。
    title 只写非空;无侧车(没 RunEnd 的 run)也更新内存态,下次落盘带上。"""
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be empty")
    sess = session_manager.get(run_id)
    if sess:
        sess.title = title
    set_run_title(run_id, title)   # 无侧车时 no-op;有侧车同步落盘
    return {"ok": True, "title": title}


@app.post("/sessions")
async def create_session():
    """创建 chat session(= 新 run_id + 共享 messages + Persister append 模式)。
    SessionState.create 用 server 装配好的共享运行时依赖造会话(Session 继承工厂)。"""
    sess = session_manager.create(
        registry=_registry, model_adapter=_adapter, tool_executor=_tool_executor,
        config=_config, guardrail_runner=_guardrail_runner,
        memory_store=_memory_store, workspace=_workspace,
    )
    _start_session_loop(sess)   # 后台通知消费者(待办 A)
    return {"run_id": sess.run_id, "created_at": sess.created_at}


# fire-and-forget turn 任务的强引用集(防任务被 GC;done 回调即移除)
_turn_tasks: set[asyncio.Task] = set()


def _spawn_turn(sess: SessionState, user_input: str, *, notification=None):
    """触发一轮 turn(fire-and-forget):事件经 SSESink 进 sess.event_queue,前端从 /stream 消费。
    返回 task(调用方可 await 或忽略)。"""
    set_active_sse_queue(sess.event_queue)   # HITL 审批事件进 session 事件队列(单通道)
    task = asyncio.create_task(sess.run_turn(user_input, SSESink(sess.event_queue), notification=notification))
    _turn_tasks.add(task)
    task.add_done_callback(_turn_tasks.discard)
    return task


@app.post("/sessions/{run_id}/turn")
async def turn(run_id: str, body: TurnBody):
    """多轮:触发一轮 turn,事件走 session 常驻 SSE 流(GET /sessions/{id}/stream)。

    单通道(修"一会话三通道"):不再 per-turn 建队列 + 在 POST 响应里流回;run_turn 的
    事件直接进 sess.event_queue,前端从 /stream 订阅(用户 turn 与自动 turn 同一条流)。
    turn 触发即返回 202,RunStart/RunEnd 由前端从流里拿(驱动 streaming 状态)。"""
    sess = ensure_session(run_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    _spawn_turn(sess, body.input)
    return {"ok": True, "run_id": sess.run_id}


@app.get("/sessions")
async def list_sessions():
    """列出所有 run 摘要(喂 sidebar)。优先读 run_meta 侧车,无则扫 transcript 末尾。"""
    return list_runs()


@app.get("/sessions/{run_id}")
async def get_session(run_id: str):
    """单 run 指标(token/step/tool/cached)。"""
    rep = read_run_report(run_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="run not found")
    return rep.to_dict()


async def _stream_gen(sess: SessionState):
    """会话事件流生成器(常驻 SSE data 行):消费 sess.event_queue 的 web 契约事件。
    独立命名以便测试直接驱动(queue -> SSE 行);端点只是 StreamingResponse 薄壳。"""
    while True:
        ev = await sess.event_queue.get()
        if not is_web_event(ev):
            continue   # delta/机制事件:CLI/tracer 已消费,web 无需(吞掉不转发)
        yield f"data: {json.dumps(_event_to_dict(ev), ensure_ascii=False)}\n\n"


@app.get("/sessions/{run_id}/stream")
async def stream_session(run_id: str):
    """会话事件流(单通道):常驻 SSE,消费 sess.event_queue 的全部 web 契约事件。

    用户 turn(POST /turn 触发)与自动 turn(session loop)的事件都进 sess.event_queue,
    前端开一条 EventSource 订阅即拿到全部。连接断开会话内事件在队列缓冲,重连后补发。
    RunEnd 不 break(持久流,前端凭 RunStart/RunEnd 落 streaming 状态)。"""
    sess = ensure_session(run_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")
    return StreamingResponse(_stream_gen(sess), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _transcript_to_messages(run_id: str) -> list[dict]:
    """读 transcript.jsonl -> 前端 ChatMessage 列表(恢复历史)。

    - user -> user 消息(跳过系统注入:[系统提示]/[task-notification]/[plan step]/[子任务])
    - assistant -> assistant 消息(content=text, thinking 从 thinking 恢复, usage 从 usage 恢复,
      toolCalls 从 tool_calls 构造,phase=done)
    - tool_result -> 关联到前一个 assistant 的 toolCall(按 call_id),填 ok/summary/error_type/error_message
    - elapsedMs 不填(ToolResult 无,在 ToolEnd 事件)
    """
    msgs: list[dict] = []
    try:
        records = list(read_transcript(run_id))
    except Exception:
        return []
    for rec in records:
        t = rec.get("type")
        if t == "user":
            content = rec.get("content", "")
            if not isinstance(content, str):
                continue
            if content.startswith(("[系统提示]", "[task-notification]", "[plan step", "[子任务")):
                continue
            msgs.append({
                "id": rec.get("uuid", f"u{len(msgs)}"),
                "role": "user",
                "content": content,
                "createdAt": int(rec.get("ts", 0) * 1000),
            })
        elif t == "assistant":
            text = rec.get("text", "") or ""
            tool_calls = rec.get("tool_calls", []) or []
            tcs = []
            for tc in tool_calls:
                args = tc.get("arguments", {}) or {}
                tcs.append({
                    "callId": tc.get("call_id", ""),
                    "toolName": tc.get("tool_name", ""),
                    "arguments": args,
                    "argumentsJson": json.dumps(args, ensure_ascii=False),
                    "phase": "done",
                })
            msg = {
                "id": rec.get("uuid", f"a{len(msgs)}"),
                "role": "assistant",
                "content": text,
                "toolCalls": tcs if tcs else None,
                "streaming": False,
                "status": "completed",
                "createdAt": int(rec.get("ts", 0) * 1000),
            }
            # Phase 1 §1.2:thinking/usage 已随 log_assistant 落盘,恢复历史能拿回(不用再等流式)
            if rec.get("thinking"):
                msg["thinking"] = rec["thinking"]
            if rec.get("usage"):
                msg["usage"] = rec["usage"]
            msgs.append(msg)
        elif t == "tool_result":
            result = rec.get("result", {}) or {}
            call_id = result.get("call_id")
            ok = result.get("ok", False)
            if not call_id:
                continue
            # 找最后一个 assistant 消息的 toolCall(按 call_id)填执行结果
            for m in reversed(msgs):
                if m.get("role") == "assistant" and m.get("toolCalls"):
                    for tc in m["toolCalls"]:
                        if tc.get("callId") == call_id:
                            tc["phase"] = "done" if ok else "error"
                            tc["ok"] = ok
                            tc["summary"] = (result.get("text") or "")[:300] or None
                            # Phase 1 §1.3:错误差异化展示(error_type/error_message 驱动)
                            err = result.get("error") or {}
                            if err and not ok:
                                tc["errorType"] = err.get("type", "ToolError")
                                tc["errorMessage"] = (err.get("message") or "")[:300] or None
                            break
                    break
    return msgs


@app.get("/sessions/{run_id}/messages")
async def get_messages(run_id: str):
    """恢复历史消息。优先重放 events.jsonl(前端事件流:精确还原直播画面,含 thinking/每步
    usage/真实耗时);老 run(无 events.jsonl)退化读 transcript 转 ChatMessage(兼容既有数据)。
    前端按 source 分支:events -> 过 eventReducer 重放;transcript -> 直接用 messages。"""
    events = read_events(run_id)
    if events is not None:
        return {"source": "events", "events": events}
    return {"source": "transcript", "messages": _transcript_to_messages(run_id)}


@app.delete("/sessions/{run_id}")
async def close_session(run_id: str):
    """关闭 session(log_run_end + close persister)。"""
    ok = session_manager.close(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": ok}


def main():
    """本地启动:cd code && python -m chatweb.backend.server(须在 code/ 下,PERSIST_ROOT 相对路径)。
    端口默认 8000;若被占(如 monitor_demo 跑在 8000),用 AGENT_PORT=8001 python -m chatweb.backend.server,
    并在 chat-template/.env.local 设 AGENT_API=http://localhost:8001 对应。"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("AGENT_PORT", "8000")))


if __name__ == "__main__":
    main()
