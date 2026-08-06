# web/session_manager.py - 多轮 chat session 管理(对齐 REPL run_agent_loop 的 session 模型)
#
# 对话产品是多轮(共享上下文)。agentloop()(agentloop.py:484)单次自洽会 close persister,
# 直接用会丢上下文。所以 web 不调 agentloop,改调 _run_turn(agentloop.py:274,单轮体不收尾),
# 由 SessionManager 管 session 级状态:一个 chat session = 一个 run_id(共享 transcript,跨轮 append)。
# 等价于把 REPL 的 _do_turn(agentloop.py:553)HTTP 化。见 chat-template-integration §3。
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from ..core.messages import Message
from ..persist.persister import Persister
from ..tracing import Tracer, TraceStore


@dataclass
class SessionState:
    """一个 chat session 的跨轮状态(adapter/registry/tool_executor 跨 session 共享,这里只存 per-session)。"""
    run_id: str
    messages: list  # 跨轮累积上下文(内存共享 list,同 REPL run_agent_loop L545)
    persister: Persister          # append 模式,跨轮不 close(session 关闭才 close)
    tracer: Tracer                # 会话级 tracer(跨轮累积 span,每轮末落 run_meta)
    created_at: float = field(default_factory=time.time)

    def close(self):
        self.persister.close()


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
