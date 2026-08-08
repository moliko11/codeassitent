# agent/session.py - 多轮会话抽象(CLI REPL / web / desktop 三端共用)
#
# 解决"一份会话逻辑两处实现"(REPL run_agent_loop 局部变量 vs web SessionState):
# 把"一个会话"的状态(run_id/messages/persister/tracer/event_store/notify_queue/turn_lock/
# title/file_history)+ 一轮 turn 的公共机制(AgentState 组装 / RuntimeContext / _runtime_state
# 注入 / messages 同步 / RunEnd / run_meta 落盘)收进 core Session。
#
# 前端只负责三件事(差异留在前端):
#   1. 装配一次共享运行时依赖(registry/adapter/executor/config/...)-> Session.create
#   2. 往哪个 frontend_sink 推事件(printer / SSESink)
#   3. 触发 turn(用户输入 session.run_turn;后台通知经 session.notify_queue + run_turn)
# REPL:阻塞输入循环 + 控制台打印;web:HTTP turn + 自动 turn 长轮询。
#
# 依赖方向:session -> agentloop(_run_turn 等,agentloop 不反向依赖 session,无循环)。
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .core.state import AgentState
from .core.workspace import Workspace
from .runtime import RuntimeContext
from .config.config import AgentConfig
from .adapters.base import BaseModelAdapter
from .tools import _runtime_state
from .tools.registry import ToolRegistry, ToolExecutor
from .guardrails import GuardrailRunner
from .memory.store import MemoryStore
from .persist.persister import Persister
from .streaming.sink import EventSink, CompositeSink
from .streaming.event_store import EventStore
from .streaming.events import RunStart, TaskNotification
from .tracing import Tracer, TraceStore, MetricsCollector
from .runner import _run_turn, _emit_run_end
from .agentloop import _first_user_title, _write_run_meta


@dataclass
class Session:
    """一个多轮会话:状态 + 共享运行时依赖 + turn 公共机制。

    一个 chat session = 一个 run_id(共享 transcript/events,跨轮 append)。
    run_turn 是公共机制:持 turn_lock 串行(用户 turn 与后台自动 turn 互斥)、
    同步 messages、发 RunEnd、落 run_meta。前端差异(事件转发/输入触发)留在前端。
    """

    # ── 会话级状态(跨轮共享) ──
    run_id: str
    messages: list = field(default_factory=list)        # 跨轮累积上下文(给模型的上下文,同 CC query messages)
    persister: Optional[Persister] = None               # append 模式,跨轮不 close(session 关闭才 close)
    tracer: Optional[Tracer] = None                     # 会话级 tracer(跨轮累积 span,每轮末落 run_meta)
    event_store: Optional[EventStore] = None            # 事件流落盘(events.jsonl,跨轮 append)
    title: str = ""                                     # 首轮自动推导 / 用户重命名(覆写 run_meta)
    created_at: float = field(default_factory=time.time)
    file_history: Optional[object] = None               # 版本链条(FileHistory,桌面 diff 数据源)
    notify_queue: asyncio.Queue = field(default_factory=asyncio.Queue)   # 后台 subagent 完成通知
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)        # 用户/自动 turn 串行(CC queryGuard)

    # ── 共享运行时依赖(create() 装配;直接构造可 None = 测试/无 run 能力) ──
    registry: Optional[ToolRegistry] = None
    model_adapter: Optional[BaseModelAdapter] = None
    tool_executor: Optional[ToolExecutor] = None
    config: Optional[AgentConfig] = None
    guardrail_runner: Optional[GuardrailRunner] = None
    memory_store: Optional[MemoryStore] = None
    workspace: Optional[Workspace] = None

    @classmethod
    def create(cls, *, registry, model_adapter, tool_executor, config,
               guardrail_runner=None, memory_store=None, workspace=None,
               file_history=None, run_id=None, messages=None, title="") -> "Session":
        """用共享运行时依赖装配一个可跑的会话(三端 entry point 共用)。
        run_id 缺省生成;传入既有 run_id 则复用同一 transcript/events(append 续写,resume 用)。
        messages/title 用于 resume 重建(缺省空会话)。子类(如 web SessionState)继承本工厂。"""
        run_id = run_id or str(uuid.uuid4())
        return cls(
            run_id=run_id,
            messages=messages if messages is not None else [],
            persister=Persister(run_id),
            tracer=Tracer(run_id, store=TraceStore(run_id)),
            event_store=EventStore(run_id),
            title=title,
            registry=registry, model_adapter=model_adapter, tool_executor=tool_executor,
            config=config, guardrail_runner=guardrail_runner, memory_store=memory_store,
            workspace=workspace, file_history=file_history,
        )

    # ─────────────────── turn 公共机制 ───────────────────

    def make_turn_sink(self, *frontend_sinks) -> EventSink:
        """一个 turn 的完整 sink 链:前端 sink(printer/SSE)+ 会话级 tracer + event_store。"""
        base = CompositeSink(*frontend_sinks)
        if self.tracer is not None:
            base = CompositeSink(base, self.tracer)
        if self.event_store is not None:
            base = CompositeSink(base, self.event_store)
        return base

    async def run_turn(self, user_input: str, frontend_sink: EventSink,
                       *, notification: Optional[tuple] = None, finalize: bool = True) -> AgentState:
        """跑一轮的公共机制(用户 turn 与后台自动 turn 共用)。

        - 新 AgentState(共享 self.messages;max_steps 是单轮上限,不继承历史 step 预算)
        - 组装 RuntimeContext + 每轮注入 _runtime_state(model_adapter/workspace/file_history,
          防跨 session ContextVar 泄漏)
        - 持 turn_lock 串行(用户 turn 与后台自动 turn 互斥;REPL 单线程锁无竞争)
        - 发 RunStart(notification 非 None 先发 TaskNotification)-> _run_turn
          -> 锁内同步 self.messages -> 发 RunEnd(finalize=True 时)
        - 收尾:标题推导 + 增量落盘 run_meta(崩在下一轮前也保留;finalize=True 时)
        finalize=False:子 agent 用(它是父 run 的一部分)——不发 RunEnd、不写 run_meta,
        事件经共享 frontend_sink 进父 trace/events。
        异常兜底:state.fail(照发 RunEnd 仅 finalize=True,不让一轮崩溃带崩 session)。
        事件经 frontend_sink 转发给调用方,调用方负责自己的通道(SSE/渲染)。
        """
        if self.config is None or self.model_adapter is None:
            raise RuntimeError("Session 未装配运行时依赖(config/model_adapter),不能 run_turn")
        state = AgentState(run_id=self.run_id, max_steps=self.config.max_steps, messages=self.messages)
        state.session_id = self.run_id
        sink = self.make_turn_sink(frontend_sink)
        ctx = RuntimeContext(
            registry=self.registry, model_adapter=self.model_adapter,
            tool_executor=self.tool_executor, config=self.config, state=state,
            sink=sink, persist=True,
            guardrail_runner=self.guardrail_runner, memory_store=self.memory_store,
            workspace=self.workspace, notify_queue=self.notify_queue,
        )
        # 单一注入点(turn_context 统一设 model_adapter/workspace/file_history 并退出恢复,
        # 根除 _runtime_state 手动 .set() 泄漏;多 Agent/REPL/web 同一套)
        with _runtime_state.turn_context(self.model_adapter, self.workspace, self.file_history):
            try:
                async with self.turn_lock:
                    if notification is not None:
                        role, text, status = notification
                        sink.emit(TaskNotification(run_id=self.run_id, role=role, status=status, text=text))
                    sink.emit(RunStart(run_id=self.run_id))
                    try:
                        state = await _run_turn(user_input, state, ctx, self.persister)
                    finally:
                        # 锁内同步 messages:任何退出路径都 sync,防自动 turn 拿到过期上下文
                        self.messages = state.messages
            except Exception as e:
                if not state.is_terminal():
                    state.fail({"type": type(e).__name__, "message": str(e)})
        if finalize:
            # 收尾(发 RunEnd + 落 run_meta)。子 agent(finalize=False)不发 turn 边界事件、
            # 不写 run_meta——它是父 run 的一部分,事件经共享 sink 进父 trace/events。
            _emit_run_end(state, sink)
            self._finalize(state)
        return state

    def _finalize(self, state: AgentState) -> None:
        """turn 收尾:标题推导 + 增量落盘 run_meta(REPL/web 共用)。"""
        if not self.title:
            self.title = _first_user_title(state.messages)
        try:
            rep = MetricsCollector().collect(self.tracer.trace)
            _write_run_meta(state, rep, self.config.model, title=self.title or None)
        except Exception:
            pass   # 收尾失败不影响主流程(同旧 run_meta 容错)

    # ─────────────────── 通知 / 收尾 ───────────────────

    @staticmethod
    def notification_input(role: str, text: str, status: str) -> str:
        """后台 subagent 完成通知 -> 注入主 agent 的 user 消息(对齐 CC 通知格式)。"""
        return f"[task-notification] {role} 完成(status={status}):\n{text}"

    def close(self, *, status=None, error=None) -> None:
        """关闭会话:可选 log_run_end(REPL 退出时带最后状态)+ 关 persister/event_store。幂等。"""
        if status is not None and self.persister is not None:
            self.persister.log_run_end(status, error)
        if self.persister is not None:
            self.persister.close()
        if self.event_store is not None:
            self.event_store.close()
