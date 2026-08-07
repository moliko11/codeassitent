# guardrails/confirmer.py - 异步确认器(对标 CC canUseTool 的 ask -> await 人)
#
# 为什么 async:web 后端无 stdin,要推前端 + await 回传;CLI 也用 async 接口(run_in_executor
# 包 input),三端共用同一接口。CC 的 canUseTool 本身就是 async(loop 级、工具执行前)。
#
# 两档(见 docs/topics/hitl-approval-design.md §2):
# - A 档(连接保持):await future,人不走时 future.set_result 继续(CLI/Desktop/Web-SSE)
# - B 档(连接可断):persisting_confirmer 抛 SuspendApproval,持久化 waiting_approval + 释放
#   loop + resume 续跑(Mobile/云,Phase 6 做)。本文件先放信号,不接 agentloop。
#
# 注入方式:ToolExecutor(..., confirmer=cli_confirmer/web_confirmer/persisting_confirmer)。
# 默认 cli_confirmer(fail-closed:非 tty 直接拒绝)。
import asyncio
import sys
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass
class ApprovalRequest:
    """批准请求:给人/前端看的信息(对标 CC PermissionRequest)。"""
    tool_name: str
    reason: str
    arguments: dict
    call_id: str = ""
    request_id: str = ""   # 前端回传时配对用(B 档持久化 key)


@dataclass
class ApprovalDecision:
    allow: bool
    reason: str = ""
    updated_input: Optional[dict] = None  # 进阶:对标 CC updatedInput,确认时改入参(选学)


# async Confirmer 协议。impl:CLI(run_in_executor input)/Web(await future)/Mobile(持久化)。
Confirmer = Callable[[ApprovalRequest], Awaitable["ApprovalDecision"]]


class SuspendApproval(Exception):
    """B 档信号:连接可断,confirmer 不 await 而是持久化挂起后抛此异常。
    agentloop 捕获 -> transition(waiting_approval) -> 落盘 -> 释放 loop。Phase 6 接。"""
    def __init__(self, request: ApprovalRequest):
        self.request = request


# ---- A 档 impl:CLI ----
def _input_confirm_sync(req: ApprovalRequest) -> ApprovalDecision:
    """同步 input(供 run_in_executor 调,不卡事件循环)。非 tty fail-closed。"""
    if not sys.stdin.isatty():
        return ApprovalDecision(allow=False,
            reason=f"非交互环境,需批准的工具 {req.tool_name} 被拒绝(fail-closed)")
    try:
        print(f"\n[需批准] {req.tool_name}: {req.reason}")
        print(f"  入参: {req.arguments}")
        ans = input("允许执行? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ApprovalDecision(allow=False, reason="用户取消")
    if ans in ("y", "yes"):
        return ApprovalDecision(allow=True)
    return ApprovalDecision(allow=False, reason=f"用户拒绝执行 {req.tool_name}")


async def cli_confirmer(req: ApprovalRequest) -> ApprovalDecision:
    """CLI/Desktop:input 阻塞丢线程池,接口是 async(对标 CC await 弹窗)。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _input_confirm_sync, req)


# ---- A 档 impl:Web(SSE 开)----
_pending_approvals: dict[str, asyncio.Future] = {}   # request_id -> future
_default_sse_queue: Optional[asyncio.Queue] = None    # configure_web_approvals 注入(单队列兜底)
# 每 turn 的 SSE 队列用 ContextVar 注入(server.py turn handler set):多 session 并发时各 turn
# 的 web_confirmer 只看到自己那趟连接的队列,不会互相串(对齐 _runtime_state 的 ContextVar 模式)。
_active_sse_queue: ContextVar = ContextVar("active_sse_queue", default=None)

WEB_APPROVAL_TIMEOUT = 300.0   # 秒;前端无响应超时自动拒绝(防 SSE 断连永久挂起,plan §0.7 临时方案)


def configure_web_approvals(sse_queue: asyncio.Queue):
    """模块级注入默认 SSE 队列(简单单队列场景;多队列并发用 set_active_sse_queue)。"""
    global _default_sse_queue
    _default_sse_queue = sse_queue


def set_active_sse_queue(sse_queue: asyncio.Queue):
    """server.py 每 turn 调:把当前连接的 SSE 队列写进 ContextVar,web_confirmer 从里取。"""
    _active_sse_queue.set(sse_queue)


async def web_confirmer(req: ApprovalRequest) -> ApprovalDecision:
    """Web(SSE 开):推 ApprovalRequestEvent 给前端 + await future。
    POST /approve/{request_id} 解 future(server.py 路由)。超时自动拒绝。"""
    queue = _active_sse_queue.get() or _default_sse_queue
    if queue is None:
        return ApprovalDecision(allow=False, reason="web approvals 未配置(SSE 连接未建立)")
    if not req.request_id:
        req.request_id = str(uuid.uuid4())
    from ..streaming.events import ApprovalRequestEvent
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _pending_approvals[req.request_id] = fut
    try:
        await queue.put(ApprovalRequestEvent(
            request_id=req.request_id, tool_name=req.tool_name,
            reason=req.reason, arguments=req.arguments,
        ))
    except Exception as e:
        _pending_approvals.pop(req.request_id, None)
        return ApprovalDecision(allow=False, reason=f"推送审批请求失败:{e}")
    try:
        return await asyncio.wait_for(fut, timeout=WEB_APPROVAL_TIMEOUT)
    except asyncio.TimeoutError:
        _pending_approvals.pop(req.request_id, None)
        return ApprovalDecision(allow=False, reason="审批超时,已自动拒绝")


def resolve_web_approval(request_id: str, decision: ApprovalDecision):
    """POST /approve/{request_id} 路由调:解 future,让 web_confirmer 的 await 继续。"""
    fut = _pending_approvals.pop(request_id, None)
    if fut and not fut.done():
        fut.set_result(decision)


# ---- B 档 impl:Mobile/云(连接可断,Phase 6 接)----
async def persisting_confirmer(req: ApprovalRequest) -> ApprovalDecision:
    """Mobile/云:不 await,持久化挂起后抛 SuspendApproval(见设计 §4.6)。
    agentloop 捕获 -> waiting_approval + 落盘 + 释放;人答完 resume() 续跑。"""
    raise SuspendApproval(req)
