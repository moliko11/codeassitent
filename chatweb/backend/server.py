# web/server.py - FastAPI 网关:HTTP/SSE 端点 + build_runtime_context 工厂
#
# 三层链路的 Python 端(对齐 chat-template-integration §2/§6):
#   Next.js BFF -> 本 server(FastAPI,本地 :8000)-> code/agent 核心(零改动)
#
# 端点:
#   POST /sessions            创建 session(新 run_id + state)
#   POST /sessions/:id/turn   多轮:复用 state 跑 _run_turn,SSE 流回(POST + ReadableStream,不用 EventSource)
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
from agent import tools as _tools
from agent.config.provider import load_provider_config, make_adapter
from agent.config.loader import (
    build_agent_config, build_guardrail_runner, build_memory_params,
    build_tool_executor_params, get_section,
)
from agent.core.state import AgentState, _ser
from agent.core.workspace import Workspace
from agent.runtime import RuntimeContext
from agent.streaming.sink import CompositeSink
from agent.streaming.sse_sink import SSESink
from agent.streaming.events import RunStart, RunEnd, StreamEvent
from agent.tracing import Tracer, TraceStore
from agent.tracing.metrics import MetricsCollector
from agent.persist.paths import memory_dir, PERSIST_ROOT
from agent.persist.store import list_runs, read_run_report, read_transcript, set_run_title
from agent.persist.persister import Persister
from agent.memory import MemoryStore
from agent.tools.memory_tool import make_save_memory_tool
from agent.tools.task_tool import make_task_tool
from agent.tools import _runtime_state
from agent.agentloop import _run_turn, _emit_run_end, _write_run_meta, _first_user_title
from agent.persist.replay import resume
from agent.prompts import build_system_prompt
from agent.core.messages import Message
from agent.guardrails.confirmer import (
    ApprovalDecision, web_confirmer, set_active_sse_queue, resolve_web_approval,
)

from .session_manager import SessionManager, SessionState


# ─────────────────── 装配(模块级共享件,对齐 main() agentloop.py:618)───────────────────

_pc = load_provider_config()   # provider 默认走 provider.yaml(default: openai_compatible);AGENT_PROVIDER env 可覆盖
if not _pc.api_key:
    raise RuntimeError(f"未设置 {_pc.provider} 的 API key,请在 code/.env 配置对应 key")
_adapter = make_adapter(_pc)
_config = build_agent_config({"model": _pc.model})
_workspace = Workspace(root=Path.cwd())  # web server 须在 code/ 下启动(同 REPL,PERSIST_ROOT 相对路径)

_registry = _tools.registry
# guardrail 链(guardrails.yaml 控制启用清单;未知 guard 名 fail-fast)
_guardrail_runner = build_guardrail_runner()
# 可靠性四件套 + 执行参数(reliability.yaml)
from agent.tools.registry import ToolExecutor
_tool_executor = ToolExecutor(
    _registry,
    before_mutation=None,            # web 暂不接 file_history 版本链条(桌面端 diff 视图才需要,TODO)
    guardrail_runner=_guardrail_runner,
    config=_config,
    confirmer=web_confirmer,         # 阶段0(Phase A):HITL 走 web_confirmer(推前端弹窗+await future)
    **build_tool_executor_params(),
)
# 工具超时/截断参数(tools.yaml)
from agent.tools.settings import configure_tools
configure_tools(get_section("tools"))
# memory + 工具注册(同 main L650-657)
_memory_store = MemoryStore(memory_dir(), **build_memory_params())
_registry.register(make_save_memory_tool(_memory_store))
try:
    _registry.register(make_task_tool())   # Task 工具(主 agent 派子 agent)
except Exception:
    pass  # 已注册则跳过

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
    # 复用同一 transcript(append 模式续写,不新建 run_id)+ 新 tracer
    sess = SessionState(
        run_id=run_id,
        messages=state.messages,
        persister= Persister(run_id),
        tracer=Tracer(run_id, store=TraceStore(run_id)),
        title=_first_user_title(state.messages),   # Phase 1 §1.1:重建时从历史首条 user 推导
    )
    session_manager._sessions[run_id] = sess  # 缓存,warm path 下次直接命中
    return sess


def build_runtime_context(state: AgentState, sink, tracer: Tracer, notify_queue: asyncio.Queue) -> RuntimeContext:
    """装配一次 turn 的 RuntimeContext。adapter/registry/tool_executor 跨 session 共享,state per-session。
    对齐 REPL _do_turn(agentloop.py:553)的装配。"""
    return RuntimeContext(
        registry=_registry,
        model_adapter=_adapter,
        tool_executor=_tool_executor,
        config=_config,
        state=state,
        sink=sink,
        persist=True,
        guardrail_runner=_guardrail_runner,
        memory_store=_memory_store,
        workspace=_workspace,
        notify_queue=notify_queue,
    )


def _event_to_dict(ev: StreamEvent) -> dict:
    """事件 -> JSON dict,加 `type` 标签(前端 reducer 按它分发)。用 _ser 跳 raw(同 transcript)。"""
    d = _ser(ev)
    d["type"] = type(ev).__name__
    return d


# ─────────────────── FastAPI app ───────────────────

app = FastAPI(title="ez-interview agent web")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # BFF 模式同源免 CORS;这里放开方便前端直连测试
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    """创建 chat session(= 新 run_id + 共享 messages + Persister append 模式)。"""
    sess = session_manager.create()
    return {"run_id": sess.run_id, "created_at": sess.created_at}


@app.post("/sessions/{run_id}/turn")
async def turn(run_id: str, body: TurnBody):
    """多轮:复用 session state 跑 _run_turn,SSE 流式回事件(POST + ReadableStream)。

    端点结构(对齐 chat-template-integration §6):
    - 一个 turn 一个 asyncio.Queue + SSESink + 临时 state(共用 session 的 messages)
    - _run_turn 在后台 task 跑,事件经 SSESink 入队
    - gen() 消费队列 -> SSE data 行;RunEnd 收尾 break
    - turn 结束同步 messages 回 session(跨轮上下文,同 REPL _do_turn L588)
    """
    sess = ensure_session(run_id)
    if not sess:
        raise HTTPException(status_code=404, detail="session not found")

    q: asyncio.Queue = asyncio.Queue()
    # HITL(阶段0):把本 turn 的 SSE 队列写进 ContextVar,web_confirmer 推 approval_request 事件到
    # 前端弹窗。set 在 create_task 前 -> run_and_signal 子任务继承(多 session 并发互不串)。
    set_active_sse_queue(q)
    sse_sink = SSESink(q)
    sink = CompositeSink(sse_sink, sess.tracer)   # 事件同时进 SSE 队列 + tracer(零侵入,同 agentloop L493)

    state = AgentState(run_id=sess.run_id, max_steps=_config.max_steps, messages=sess.messages)
    state.session_id = sess.run_id
    notify_queue: asyncio.Queue = asyncio.Queue()
    ctx = build_runtime_context(state=state, sink=sink, tracer=sess.tracer, notify_queue=notify_queue)

    # _runtime_state 注入(对齐 agentloop L496-498:_runtime_state 给 _run_steps 内的工具用)
    _runtime_state.model_adapter.set(_adapter)     # WebFetch 用
    _runtime_state.workspace.set(_workspace)       # 路径权限校验用(file_history 暂不接,None=跳过 snapshot)

    async def run_and_signal():
        """跑 _run_turn,完成后发 RunEnd(对齐 REPL _do_turn 调 _emit_run_end)。"""
        try:
            await _run_turn(body.input, state, ctx, sess.persister)
        except Exception as e:
            state.fail({"type": "WebTurnError", "message": str(e)})
        finally:
            _emit_run_end(state, sink)   # 发 RunEnd 进 sink -> 入 SSE 队列 -> gen 收到 break

    async def gen():
        sink.emit(RunStart(run_id=sess.run_id))   # 开场事件(对齐 REPL _do_turn L576)
        task = asyncio.create_task(run_and_signal())
        try:
            while True:
                ev = await q.get()
                yield f"data: {json.dumps(_event_to_dict(ev), ensure_ascii=False)}\n\n"
                if isinstance(ev, RunEnd):
                    break
            await task
        finally:
            # 同步跨轮上下文(append 返回 copy,state.messages 已离开原 list,同 REPL bug2 修复)
            sess.messages = state.messages
            # Phase 1 §1.1:首轮自动推导标题(仅当用户未重命名过;重命名过的用用户值,不被覆盖)
            if not sess.title:
                sess.title = _first_user_title(state.messages)
            # 增量落盘 run_meta(对齐 REPL _do_turn L587:每轮末落,崩在下一轮前也保留)
            try:
                rep = MetricsCollector().collect(sess.tracer.trace)
                _write_run_meta(state, rep, _config.model, title=sess.title or None)
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
    """恢复历史消息(读 transcript 转 ChatMessage)。"""
    return _transcript_to_messages(run_id)


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
