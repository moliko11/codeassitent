# web/session_manager.py - 多轮 chat session 管理(对齐 REPL run_agent_loop 的 session 模型)
#
# 对话产品是多轮(共享上下文)。agentloop()(agentloop.py:484)单次自洽会 close persister,
# 直接用会丢上下文。所以 web 不调 agentloop,改调 _run_turn(agentloop.py:274,单轮体不收尾),
# 由 SessionManager 管 session 级状态:一个 chat session = 一个 run_id(共享 transcript,跨轮 append)。
# 等价于把 REPL 的 _do_turn(agentloop.py:553)HTTP 化。见 chat-template-integration §3。
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from agent.core.messages import Message
from agent.persist.persister import Persister
from agent.tracing import Tracer, TraceStore


@dataclass
class SessionState:
    """一个 chat session 的跨轮状态(adapter/registry/tool_executor 跨 session 共享,这里只存 per-session)。"""
    run_id: str
    messages: list  # 跨轮累积上下文(内存共享 list,同 REPL run_agent_loop L545)
    persister: Persister          # append 模式,跨轮不 close(session 关闭才 close)
    tracer: Tracer                # 会话级 tracer(跨轮累积 span,每轮末落 run_meta)
    created_at: float = field(default_factory=time.time)
    title: str = ""               # Phase 1 §1.1:会话标题(首轮自动推导,前端可重命名,覆写 run_meta)
    file_history: Optional[object] = None   # Phase 2 §2.5:跨轮复用的 FileHistory(桌面 diff 数据源)

    def close(self):
        self.persister.close()


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
