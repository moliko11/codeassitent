# web/session_manager.py - 多轮 chat session 管理(对齐 REPL run_agent_loop 的 session 模型)
#
# 对话产品是多轮(共享上下文)。agentloop()(agentloop.py:484)单次自洽会 close persister,
# 直接用会丢上下文。所以 web 不调 agentloop,改调 _run_turn(agentloop.py:274,单轮体不收尾),
# 由 SessionManager 管 session 级状态:一个 chat session = 一个 run_id(共享 transcript,跨轮 append)。
# 等价于把 REPL 的 _do_turn(agentloop.py:553)HTTP 化。见 chat-template-integration §3。
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from agent.core.messages import Message
from agent.persist.persister import Persister
from agent.tracing import Tracer, TraceStore
from agent.streaming.event_store import EventStore


@dataclass
class SessionState:
    """一个 chat session 的跨轮状态(adapter/registry/tool_executor 跨 session 共享,这里只存 per-session)。

    后台通知闭环(待办 A,对齐 CC 命令队列 + processQueueIfReady):
    - notify_queue:后台 subagent 完成通知通道(put (role, text, status));`_session_loop` 是唯一消费者,
      通知到达即自动起一轮 turn(CC:空闲自动处理,不等用户下次发消息)
    - turn_lock:turn 串行化(用户 turn vs 自动 turn,对齐 CC queryGuard 单占位;用户输入优先)
    - event_queue:自动 turn 的事件缓冲(web 无 REPL 循环,前端 long-poll GET /sessions/{id}/events 拉)
    """
    run_id: str
    messages: list  # 跨轮累积上下文(内存共享 list,同 REPL run_agent_loop L545)
    persister: Persister          # append 模式,跨轮不 close(session 关闭才 close)
    tracer: Tracer                # 会话级 tracer(跨轮累积 span,每轮末落 run_meta)
    event_store: Optional[EventStore] = None   # 会话级事件流落盘(web 契约事件 -> events.jsonl,跨轮 append)
    created_at: float = field(default_factory=time.time)
    title: str = ""               # Phase 1 §1.1:会话标题(首轮自动推导,前端可重命名,覆写 run_meta)
    file_history: Optional[object] = None   # Phase 2 §2.5:跨轮复用的 FileHistory(桌面 diff 数据源)
    notify_queue: asyncio.Queue = field(default_factory=asyncio.Queue)   # 后台 subagent 完成通知通道
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)    # 自动 turn 事件缓冲(前端 /events 拉)
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)        # turn 串行(用户/自动互斥,CC queryGuard)
    loop_task: Optional[asyncio.Task] = None   # 会话级通知消费者 loop(server _start_session_loop 挂)

    def close(self):
        if self.loop_task is not None:
            self.loop_task.cancel()
        self.persister.close()
        if self.event_store is not None:
            self.event_store.close()


def make_file_history(run_id: str):
    """构建该 run 的 FileHistory(桌面 diff 视图数据源,Phase 2 §2.5)。

    - 挂 on_snapshot 回调:每步快照 append 一行到 file-history-meta.jsonl sidecar。
      FileHistory 元数据(snapshots/tracked_files)纯内存,sidecar 让历史 run 也能看版本链。
    - 若 sidecar 已存在则全量重建(进程重启 / resume 旧 run 时版本连续)。
    """
    from agent.utils.fileHistory import FileHistory, Snapshot, FileBackup
    from agent.persist.paths import run_dir

    rdir = run_dir(run_id)
    meta_p = rdir / "file-history-meta.jsonl"

    def _writer(snap):
        with open(meta_p, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_id": snap.step_id,
                "ts": snap.timestamp,
                "tracked": {fp: {"file": b.backup_file_name, "version": b.version, "time": b.backup_time}
                            for fp, b in snap.tracked.items()},
            }, ensure_ascii=False) + "\n")

    fh = FileHistory(rdir / "file-history", on_snapshot=_writer)
    if meta_p.exists():
        snaps = []
        for line in meta_p.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            snaps.append(Snapshot(
                d["step_id"],
                {fp: FileBackup(v["file"], v["version"], v.get("time", 0.0))
                 for fp, v in d["tracked"].items()},
                d.get("ts", 0.0),
            ))
        if snaps:
            fh.snapshots = snaps
            fh.tracked_files = set().union(*(s.tracked for s in snaps))
            fh.seq = len(snaps)
    return fh


class SessionManager:
    """{run_id -> SessionState}。create/get/close。不碰 state(adapter/registry 由 server 装配共享)。"""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}

    def create(self) -> SessionState:
        run_id = str(uuid.uuid4())
        sess = SessionState(
            run_id=run_id,
            messages=[],
            persister=Persister(run_id),
            tracer=Tracer(run_id, store=TraceStore(run_id)),
            file_history=make_file_history(run_id),   # Phase 2 §2.5:桌面 diff 数据源
            event_store=EventStore(run_id),           # 事件流落盘:web 契约事件 -> events.jsonl
        )
        self._sessions[run_id] = sess
        return sess

    def get(self, run_id: str) -> Optional[SessionState]:
        return self._sessions.get(run_id)

    def close(self, run_id: str) -> bool:
        sess = self._sessions.pop(run_id, None)
        if sess:
            sess.close()
            return True
        return False
