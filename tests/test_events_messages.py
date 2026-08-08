"""events 层消息级事件验收测试(2026-08-08,对齐 CC 双层事件模型)。

验证:
- agentloop 源头发射消息级事件:每 step 一条 AssistantMessage(带 text/thinking/tool_calls/usage),
  每条工具结果一条 ToolResultMessage(带 ok/elapsed_ms)——web 契约,不再消费 delta
- elapsed_ms 实测 > 0(修待办 C 恒 0):ToolResultMessage 带真实耗时
- web 白名单 _is_web_event:只放行消息级 + RunStart/RunEnd/ToolStart/Approval,吞 delta
不依赖真实 LLM(同 test_smoke 的 _ScriptedAdapter 模式)。
运行(从 code/,3.12 venv): python -m pytest tests/test_events_messages.py -v
"""
import asyncio
import time

import pytest

from agent.agentloop import agentloop
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.core.messages import Message
from agent.core.models import ModelResponse, TokenUsage
from agent.adapters.base import BaseModelAdapter
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.tools.defs import ToolCall, Tool, ToolSpec
from agent.streaming.sink import EventSink
from agent.streaming.events import (
    AssistantMessage, ToolResultMessage, RunStart, RunEnd, ToolStart, ApprovalRequestEvent,
    TaskNotification, StepStart, StepEnd, TextDelta, ThinkingDelta, ToolCallStart, ToolCallDelta,
    ToolCallEnd, MessageEnd, ToolEnd,
)


class RecordingSink(EventSink):
    """收集所有事件,断言用。"""

    def __init__(self):
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)


class _ToolAdapter(BaseModelAdapter):
    """前 rounds 轮返回工具调用(带 usage),之后返回 final answer。"""

    def __init__(self, rounds: int):
        super().__init__(api_key="", base_url="", model="")
        self.n = 0
        self.rounds = rounds

    async def call_llm(self, request):
        self.n += 1
        if self.n <= self.rounds:
            return ModelResponse(
                text=f"step{self.n}",
                tool_calls=[ToolCall(call_id=f"c{self.n}", tool_name="hello", arguments={"q": "x"})],
                usage=TokenUsage(input_tokens=100 + self.n, output_tokens=50,
                                 total_tokens=150 + self.n),
            )
        return ModelResponse(text="done",
                             usage=TokenUsage(input_tokens=300, output_tokens=100, total_tokens=400))

    def append_assistant(self, messages, model_response):
        new = list(messages)
        new.append(Message(role="assistant", content=model_response.text or ""))
        return new

    def append_tool_result(self, messages, result):
        new = list(messages)
        new.append(Message(role="tool", content=result.text or ""))
        return new


def _run(tool_rounds=2) -> RecordingSink:
    reg = ToolRegistry()
    reg.register(Tool(tool_spec=ToolSpec(name="hello", description="", input_schema={}),
                      handler=lambda q="": time.sleep(0.01) or "hi"))
    sink = RecordingSink()
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_ToolAdapter(tool_rounds),
        config=AgentConfig(max_steps=5),
        state=AgentState(),
        sink=sink,
    )
    asyncio.run(agentloop("hi", ctx))
    return sink


def test_assistant_and_tool_result_messages_emitted():
    """源头发消息级事件:每 step 一条 AssistantMessage,每条工具一条 ToolResultMessage。"""
    sink = _run()
    assistants = [e for e in sink.events if isinstance(e, AssistantMessage)]
    results = [e for e in sink.events if isinstance(e, ToolResultMessage)]

    # 2 工具轮 + 1 final 轮 = 3 条 AssistantMessage,各自带 step 内数据(修"只显示最后一步")
    assert len(assistants) == 3
    assert [a.text for a in assistants] == ["step1", "step2", "done"]
    assert assistants[0].usage.input_tokens == 101          # 每步 usage 独立,不互相覆盖
    assert assistants[1].usage.input_tokens == 102
    assert assistants[0].tool_calls[0]["tool_name"] == "hello"
    assert assistants[0].tool_calls[0]["call_id"] == "c1"
    assert assistants[0].tool_calls[0]["arguments"] == {"q": "x"}
    assert assistants[1].tool_calls[0]["call_id"] == "c2"
    # 每步带 run_id + uuid(CC:uuid 全程带)
    assert all(a.run_id and a.uuid for a in assistants)

    # 2 条 ToolResultMessage,带实测耗时(修待办 C 恒 0)+ ok/error_type/attempts
    assert len(results) == 2
    for r in results:
        assert r.ok is True
        assert r.elapsed_ms > 0
        assert r.tool_name == "hello"
        assert r.attempts == 1


def test_run_end_carries_turn_aggregate_usage():
    """RunEnd 带整轮聚合 usage(对齐 CC result 事件):所有 step 的 usage 累加,不是只最后一步。
    前端据此在 turn 结束时显示总账,不再逐条 assistant 消息显示 per-step usage。"""
    sink = _run(tool_rounds=2)
    ends = [e for e in sink.events if isinstance(e, RunEnd)]
    assert len(ends) == 1
    # step1(101/50/151) + step2(102/50/152) + final(300/100/400) = 503/200/703
    assert ends[0].usage == {"input_tokens": 503, "output_tokens": 200,
                             "total_tokens": 703, "cached_tokens": 0}
    assert ends[0].num_steps == 3          # 对齐 CC result.num_turns
    assert ends[0].duration_ms is not None and ends[0].duration_ms > 0


def test_tool_result_error_carries_error_type():
    """失败工具结果:ok=False + error_type(前端 phase=error 分类用)。"""
    reg = ToolRegistry()
    reg.register(Tool(tool_spec=ToolSpec(name="boom", description="", input_schema={}),
                      handler=lambda: 1 / 0))   # 执行抛 ZeroDivisionError
    sink = RecordingSink()
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_ToolAdapter(1), config=AgentConfig(max_steps=5),
        state=AgentState(), sink=sink,
    )
    asyncio.run(agentloop("hi", ctx))
    results = [e for e in sink.events if isinstance(e, ToolResultMessage)]
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error_type is not None


try:
    from chatweb.backend.server import _is_web_event   # noqa: E402
    _HAVE_SERVER = True
except Exception:
    _HAVE_SERVER = False

requires_server = pytest.mark.skipif(not _HAVE_SERVER,
                                     reason="chatweb.backend.server import 需 .env 的 API key")


@requires_server
def test_is_web_event_whitelist():
    """web 只收消息级 + 书签 + ToolStart + HITL;delta/机制事件全吞(CLI/tracer 已消费)。"""
    def mk(ev):
        return _is_web_event(ev)

    run = RunStart(run_id="r")
    assert mk(run) is True
    assert mk(RunEnd(status="completed")) is True
    assert mk(AssistantMessage(run_id="r", uuid="u", text="hi")) is True
    assert mk(ToolResultMessage(run_id="r", uuid="u", call_id="c", tool_name="read", ok=True)) is True
    assert mk(ToolStart(call_id="c", tool_name="read", arguments={})) is True
    assert mk(ApprovalRequestEvent(request_id="x", tool_name="bash", reason="r", arguments={})) is True
    assert mk(TaskNotification(run_id="r", status="completed", text="x")) is True

    for ev in (StepStart(step_index=0), StepEnd(step_index=0), TextDelta(text="x"),
               ThinkingDelta(text="x"), ToolCallStart(call_id="c", tool_name="read"),
               ToolCallDelta(call_id="c", arguments_delta="{}"), ToolCallEnd(call_id="c"),
               ToolEnd(call_id="c", tool_name="read", ok=True), MessageEnd()):
        assert mk(ev) is False, f"{type(ev).__name__} 应被 web 吞掉"


@requires_server
def test_session_loop_consumes_notify_and_runs_auto_turn():
    """待办 A:session loop 消费 notify_queue 的 (role, text, status),自动起一轮 turn。
    桩掉 _run_auto_turn 验证队列语义(不碰真实 LLM):通知只消费一次(唯一消费者 -> 天然 exactly-once),
    合成 [task-notification] 消息格式照 REPL,自动 turn 事件进 event_queue(前端 /events long-poll 拉)。"""
    from chatweb.backend import server

    async def _run():
        sess = server.SessionState(run_id="loop-test", messages=[], persister=None, tracer=None)
        calls: list[str] = []

        async def stub(sess, notification, role="subagent", status="completed", text=""):
            calls.append(notification)
            sess.event_queue.put_nowait(server.RunEnd(status="completed"))

        task = asyncio.create_task(server._session_loop(sess, run_auto_turn=stub))
        sess.notify_queue.put_nowait(("subagent", "result text", "completed"))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return calls, sess

    calls, sess = asyncio.run(_run())
    assert calls == ["[task-notification] subagent 完成(status=completed):\nresult text"]
    assert sess.notify_queue.empty()          # 只消费一次,不重复注入
    ev = sess.event_queue.get_nowait()
    assert isinstance(ev, server.RunEnd)      # 自动 turn 事件进 event_queue


@requires_server
def test_session_loop_waits_for_turn_lock():
    """待办 A:用户 turn 在跑(持锁)时,通知 turn 等待(用户输入优先,对齐 CC 优先级 next > later);
    锁释放后才自动起 turn,不抢用户。"""
    from chatweb.backend import server

    async def _run():
        sess = server.SessionState(run_id="lock-test", messages=[], persister=None, tracer=None)
        order: list[str] = []

        async def stub(sess, notification, role="subagent", status="completed", text=""):
            order.append("auto-turn")

        task = asyncio.create_task(server._session_loop(sess, run_auto_turn=stub))
        await sess.turn_lock.acquire()        # 模拟用户 turn 持锁
        sess.notify_queue.put_nowait(("subagent", "text", "completed"))
        await asyncio.sleep(0.02)
        assert order == []                    # 自动 turn 在等锁,不抢先
        sess.turn_lock.release()
        await asyncio.sleep(0.02)
        assert order == ["auto-turn"]         # 锁释放后自动起 turn
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
