# web/session_manager.py - 多轮 chat session 管理(会话机制已上收 core Session)
#
# 对话产品是多轮(共享上下文)。agentloop()(agentloop.py)单次自洽会 close persister,
# 直接用会丢上下文。会话机制(run_id/messages/persister/tracer/event_store/notify_queue/
# turn_lock + run_turn)已上收为 agent.session.Session,CLI REPL 与 web 共用:
#   - REPL:run_agent_loop 直接用一个 Session(输入循环 + 控制台)
#   - web:SessionState 继承 Session,只补 web 专属字段(event_queue/loop_task)
# Session.run_turn 内部持 turn_lock 串行(用户 turn 与自动 turn)、同步 messages、
# 发 RunEnd、落 run_meta;web 只负责 SSE/长轮询转发。见 chat-template-integration §3。
import asyncio
import json
from dataclasses import dataclass, field
from typing import Optional

from agent.session import Session


@dataclass
class SessionState(Session):
    """web 会话 = core Session(三端共用状态 + turn 机制) + web 专属事件缓冲。

    后台通知闭环(对齐 CC 命令队列 + processQueueIfReady):
    - notify_queue(继承):后台 subagent 完成通知通道;_session_loop 是唯一消费者,
      通知到达即自动起一轮 turn(不等用户下次发消息)
    - turn_lock(继承):turn 串行化(用户 turn vs 自动 turn,run_turn 内部持锁)
    - event_queue:自动 turn 的事件缓冲(web 无 REPL 循环,前端 long-poll GET /sessions/{id}/events 拉)
    - loop_task:会话级通知消费者 loop(server _start_session_loop 挂)
    """

    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    loop_task: Optional[asyncio.Task] = None

    def close(self):
        """关闭 web 会话:取消通知 loop + Session 收尾(关 persister/event_store)。"""
        if self.loop_task is not None:
            self.loop_task.cancel()
        super().close()


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
    """{run_id -> SessionState}。create/get/close。不碰共享运行时依赖(由 server 装配传入)。"""

    def __init__(self):
        self._sessions: dict[str, SessionState] = {}

    def create(self, *, registry, model_adapter, tool_executor, config,
               guardrail_runner=None, memory_store=None, workspace=None) -> SessionState:
        """新建 web 会话(用 server 装配好的共享运行时依赖;SessionState 继承 Session.create)。"""
        sess = SessionState.create(
            registry=registry, model_adapter=model_adapter, tool_executor=tool_executor,
            config=config, guardrail_runner=guardrail_runner, memory_store=memory_store,
            workspace=workspace,
        )
        self._sessions[sess.run_id] = sess
        return sess

    def get(self, run_id: str) -> Optional[SessionState]:
        return self._sessions.get(run_id)

    def close(self, run_id: str) -> bool:
        sess = self._sessions.pop(run_id, None)
        if sess:
            sess.close()
            return True
        return False
