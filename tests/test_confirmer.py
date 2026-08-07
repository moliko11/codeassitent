"""阶段0(Phase A) HITL confirmer 验收测试(hitl-approval-design.md §7 Phase A)。

覆盖:
- cli_confirmer 非 tty fail-closed(一次性 agentloop/CI 不跑写命令)
- web_confirmer:set_active_sse_queue + resolve_web_approval 解 future -> 返回 decision
- persisting_confirmer 抛 SuspendApproval(B 档信号,Phase 6 用)
- can_use_tool:mock confirmer deny/allow(high_risk + git ASK)
- execute_many 集成:deny -> ToolResult(GuardrailBlocked)回填,不执行

不依赖真实 LLM。运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_confirmer.py -v
"""

import asyncio
import sys

import pytest

from agent.guardrails.confirmer import (
    ApprovalRequest, ApprovalDecision, cli_confirmer, web_confirmer,
    set_active_sse_queue, resolve_web_approval, persisting_confirmer, SuspendApproval,
)
from agent.streaming.events import ApprovalRequestEvent
from agent.tools.defs import ToolCall, Tool, ToolSpec
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.adapters.base import BaseModelAdapter
from agent.core.models import ModelResponse
from agent.core.messages import Message


# ─────────────────── cli_confirmer ───────────────────

def test_cli_confirmer_non_tty_fail_closed(monkeypatch):
    """非 tty:cli_confirmer 拒绝(绝不静默执行),不阻塞。"""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    req = ApprovalRequest(tool_name="danger", reason="r", arguments={})
    d = asyncio.run(cli_confirmer(req))
    assert d.allow is False
    assert "fail-closed" in d.reason or "非交互" in d.reason


# ─────────────────── web_confirmer ───────────────────

def test_web_confirmer_resolve_future():
    """web_confirmer:推 ApprovalRequestEvent 到 SSE 队列 + await future;
    resolve_web_approval 解 future -> 返回该 decision。"""
    q: asyncio.Queue = asyncio.Queue()
    set_active_sse_queue(q)
    req = ApprovalRequest(tool_name="danger", reason="高风险需批准", arguments={"cmd": "x"}, request_id="w1")

    async def scenario():
        task = asyncio.ensure_future(web_confirmer(req))
        await asyncio.sleep(0.01)   # 让 web_confirmer 注册 future + 推事件
        ev = q.get_nowait()
        assert isinstance(ev, ApprovalRequestEvent)
        assert ev.request_id == "w1" and ev.tool_name == "danger" and ev.reason == "高风险需批准"
        assert ev.arguments == {"cmd": "x"}
        resolve_web_approval("w1", ApprovalDecision(allow=True, reason="用户允许"))
        return await task

    d = asyncio.run(scenario())
    assert d.allow is True


def test_web_confirmer_unconfigured_denies():
    """未配置 SSE 队列:fail-closed 拒绝(不卡死)。"""
    set_active_sse_queue(None)
    req = ApprovalRequest(tool_name="danger", reason="r", arguments={})
    d = asyncio.run(web_confirmer(req))
    assert d.allow is False


def test_web_confirmer_deny_decision():
    """resolve_web_approval 传 deny -> await web_confirmer 返回 deny。"""
    q: asyncio.Queue = asyncio.Queue()
    set_active_sse_queue(q)
    req = ApprovalRequest(tool_name="danger", reason="r", arguments={}, request_id="w2")

    async def scenario():
        task = asyncio.ensure_future(web_confirmer(req))
        await asyncio.sleep(0.01)
        resolve_web_approval("w2", ApprovalDecision(allow=False, reason="用户拒绝"))
        return await task

    d = asyncio.run(scenario())
    assert d.allow is False


# ─────────────────── persisting_confirmer(B 档信号)───────────────────

def test_persisting_confirmer_raises_suspend():
    """persisting_confirmer(连接可断 B 档):抛 SuspendApproval,不 await。"""
    req = ApprovalRequest(tool_name="danger", reason="r", arguments={})
    with pytest.raises(SuspendApproval) as ei:
        asyncio.run(persisting_confirmer(req))
    assert ei.value.request is req


# ─────────────────── 端到端:agentloop + web_confirmer(Phase A 核心)───────────────────

class _ToolThenDone(BaseModelAdapter):
    """第 1 轮返回 tool_call(danger),之后返回 final text。"""
    def __init__(self):
        super().__init__("", "", "")
        self.n = 0
    async def call_llm(self, request):
        self.n += 1
        if self.n == 1:
            return ModelResponse(tool_calls=[ToolCall(call_id="c1", tool_name="danger", arguments={})])
        return ModelResponse(text="done")
    def append_assistant(self, m, mr):
        new = list(m); new.append(Message(role="assistant", content=mr.text or "")); return new
    def append_tool_result(self, m, r):
        new = list(m); new.append(Message(role="tool", content=r.text or "")); return new


def _loop_ctx(confirmer, executed: list):
    """装配单高风险工具 registry + RuntimeContext;executed 列表记 handler 是否真跑(deny 时不该执行)。"""
    from agent.runtime import RuntimeContext
    from agent.config.config import AgentConfig
    from agent.core.state import AgentState

    reg = ToolRegistry()
    reg.register(Tool(
        tool_spec=ToolSpec(name="danger", description="d",
                           input_schema={"type": "object", "properties": {}}, high_risk=True),
        handler=lambda: executed.append("ran"),
    ))
    return RuntimeContext(
        registry=reg,
        tool_executor=ToolExecutor(reg, config=None, confirmer=confirmer),
        model_adapter=_ToolThenDone(),
        config=AgentConfig(max_steps=5),
        state=AgentState(),
    )


def test_agentloop_web_hitl_resolve_continues():
    """端到端:agentloop + web_confirmer,推 ApprovalRequestEvent 到 SSE 队列;
    resolve_web_approval(allow) 解 future -> 工具执行 -> 循环继续到 completed。"""
    from agent.agentloop import agentloop
    q: asyncio.Queue = asyncio.Queue()
    set_active_sse_queue(q)
    executed = []
    ctx = _loop_ctx(web_confirmer, executed)

    async def scenario():
        task = asyncio.ensure_future(agentloop("do danger", ctx))
        ev = await asyncio.wait_for(q.get(), timeout=5)   # 等审批请求推给前端
        assert isinstance(ev, ApprovalRequestEvent)
        assert ev.tool_name == "danger"
        resolve_web_approval(ev.request_id, ApprovalDecision(allow=True))
        return await task

    state = asyncio.run(scenario())
    assert state.status == "completed"
    assert executed == ["ran"]   # allow 后工具真的执行了


def test_agentloop_web_hitl_deny_blocks_tool():
    """端到端:resolve deny -> 工具不执行(handler 未被调),GuardrailBlocked 回填,循环完成。"""
    from agent.agentloop import agentloop
    q: asyncio.Queue = asyncio.Queue()
    set_active_sse_queue(q)
    executed = []
    ctx = _loop_ctx(web_confirmer, executed)

    async def scenario():
        task = asyncio.ensure_future(agentloop("do danger", ctx))
        ev = await asyncio.wait_for(q.get(), timeout=5)
        resolve_web_approval(ev.request_id, ApprovalDecision(allow=False, reason="用户拒绝"))
        return await task

    state = asyncio.run(scenario())
    assert state.status == "completed"
    assert executed == []   # deny:工具未被执行
    # 工具结果回填模型:GuardrailBlocked 出现在上下文里(下轮模型能看到"未获确认")
    blocked_msgs = [m.content for m in ctx.state.messages
                    if m.role == "tool" and "GuardrailBlocked" in (m.content or "")]
    assert blocked_msgs


# 注意:confirmer 协议是 async(Confirmer = Callable[..., Awaitable[ApprovalDecision]]),
# can_use_tool 里 `await self.confirmer(req)` —— mock 必须是 async def(同步返回会 TypeError)。

async def _deny(req):
    return ApprovalDecision(allow=False, reason="mock 拒绝")


async def _allow(req):
    return ApprovalDecision(allow=True)


def _high_risk_registry():
    reg = ToolRegistry()
    reg.register(Tool(
        tool_spec=ToolSpec(name="danger", description="d",
                           input_schema={"type": "object", "properties": {}}, high_risk=True),
        handler=lambda: "ok",
    ))
    return reg


def test_can_use_tool_high_risk_deny():
    """high_risk 工具 + mock confirmer deny -> can_use_tool 返回 denied。"""
    exe = ToolExecutor(_high_risk_registry(), confirmer=_deny)
    call = ToolCall(call_id="x", tool_name="danger", arguments={})
    d = asyncio.run(exe.can_use_tool(call))
    assert d.allowed is False
    assert "mock 拒绝" in d.reason


def test_can_use_tool_high_risk_allow():
    """high_risk 工具 + mock confirmer allow -> can_use_tool 放行。"""
    exe = ToolExecutor(_high_risk_registry(), confirmer=_allow)
    call = ToolCall(call_id="x", tool_name="danger", arguments={})
    d = asyncio.run(exe.can_use_tool(call))
    assert d.allowed is True


def test_can_use_tool_normal_tool_no_confirmer():
    """非高风险非 git 工具:不调 confirmer 直接放行(用会抛的 confirmer 验证不被调)。"""
    import agent.tools  # 触发 __init__.py 全量注册(getnowtime 等内置工具)

    def boom(req):
        raise AssertionError("普通工具不应调 confirmer")

    exe = ToolExecutor(agent.tools.registry, confirmer=boom)
    d = asyncio.run(exe.can_use_tool(ToolCall(call_id="c1", tool_name="getnowtime", arguments={})))
    assert d.allowed is True


# ─────────────────── execute_many 集成 ───────────────────

def test_execute_many_high_risk_deny_returns_guardrail_blocked():
    """execute_many:high_risk 工具被 mock confirmer deny -> ToolResult(GuardrailBlocked),不执行。"""
    exe = ToolExecutor(_high_risk_registry(), confirmer=_deny)
    call = ToolCall(call_id="x", tool_name="danger", arguments={})

    async def run():
        async for r in exe.execute_many([call]):
            return r

    r = asyncio.run(run())
    assert r.ok is False
    assert r.error["type"] == "GuardrailBlocked"
    assert "mock 拒绝" in r.error["message"]


def test_execute_many_high_risk_allow_executes():
    """execute_many:high_risk 工具被 mock confirmer allow -> 正常执行。"""
    exe = ToolExecutor(_high_risk_registry(), confirmer=_allow)
    call = ToolCall(call_id="x", tool_name="danger", arguments={})

    async def run():
        async for r in exe.execute_many([call]):
            return r

    r = asyncio.run(run())
    assert r.ok is True
