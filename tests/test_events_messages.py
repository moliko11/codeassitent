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
    ToolCallEnd, MessageEnd, ToolEnd, is_web_event,
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


# 会话 loop 测试需 import chatweb.backend.server(import 时读 .env 的 API key,无 key 机器跳过)。
# 白名单契约已上收为 streaming.events.is_web_event,无需 server,见下面独立测试。
try:
    from chatweb.backend.server import _session_loop   # noqa: E402
    _HAVE_SERVER = True
except Exception:
    _HAVE_SERVER = False

requires_server = pytest.mark.skipif(not _HAVE_SERVER,
                                     reason="chatweb.backend.server import 需 .env 的 API key")


def test_is_web_event_whitelist():
    """web 只收消息级 + 书签 + ToolStart + HITL + 后台通知;delta/机制事件全吞(CLI/tracer 已消费)。
    契约单点在 streaming.events.is_web_event:server SSE 过滤与 EventStore 落盘(events.jsonl)共用。"""
    assert is_web_event(RunStart(run_id="r")) is True
    assert is_web_event(RunEnd(status="completed")) is True
    assert is_web_event(AssistantMessage(run_id="r", uuid="u", text="hi")) is True
    assert is_web_event(ToolResultMessage(run_id="r", uuid="u", call_id="c", tool_name="read", ok=True)) is True
    assert is_web_event(ToolStart(call_id="c", tool_name="read", arguments={})) is True
    assert is_web_event(ApprovalRequestEvent(request_id="x", tool_name="bash", reason="r", arguments={})) is True
    assert is_web_event(TaskNotification(run_id="r", status="completed", text="x")) is True

    for ev in (StepStart(step_index=0), StepEnd(step_index=0), TextDelta(text="x"),
               ThinkingDelta(text="x"), ToolCallStart(call_id="c", tool_name="read"),
               ToolCallDelta(call_id="c", arguments_delta="{}"), ToolCallEnd(call_id="c"),
               ToolEnd(call_id="c", tool_name="read", ok=True), MessageEnd()):
        assert is_web_event(ev) is False, f"{type(ev).__name__} 应被 web 吞掉"


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

    # 注:turn 串行语义(用户 turn vs 自动 turn 互斥)已上收到 Session.run_turn 内部持锁,
    # 见 tests/test_session.py::test_run_turn_serializes_on_turn_lock(原锁测试已迁走)。


@requires_server
def test_single_channel_spawn_turn_events_into_session_queue(tmp_path, monkeypatch):
    """单通道(修"一会话三通道"):POST /turn 触发(fire-and-forget,不流回响应)->
    run_turn 事件直接进 sess.event_queue(/stream 消费),不再 per-turn 队列。"""
    import json
    from unittest import mock

    from chatweb.backend import server
    import agent.persist.paths as paths
    from agent.session import Session
    from agent.core.state import AgentState
    from agent.streaming.events import RunStart, AssistantMessage, RunEnd

    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")
    sess = server.SessionState.create(
        registry=server._registry, model_adapter=object(), tool_executor=server._tool_executor,
        config=server._config, guardrail_runner=server._guardrail_runner,
        memory_store=server._memory_store, workspace=server._workspace,
    )

    async def fake_run_turn(self, user_input, frontend_sink, *, notification=None):
        # 桩:模拟 run_turn 经 session sink 发一轮事件(frontend_sink = SSESink(sess.event_queue))
        sink = self.make_turn_sink(frontend_sink)
        sink.emit(RunStart(run_id=self.run_id))
        sink.emit(AssistantMessage(run_id=self.run_id, uuid="u1", text="hi"))
        sink.emit(RunEnd(status="completed"))
        return AgentState(run_id=self.run_id, messages=self.messages)

    async def _run():
        with mock.patch.object(Session, "run_turn", fake_run_turn):
            task = server._spawn_turn(sess, "hi")
            await task
        evs = []
        while not sess.event_queue.empty():
            evs.append(sess.event_queue.get_nowait())
        return evs

    evs = asyncio.run(_run())
    assert [type(e).__name__ for e in evs] == ["RunStart", "AssistantMessage", "RunEnd"]


@requires_server
def test_stream_gen_serves_session_queue(tmp_path, monkeypatch):
    """_stream_gen(单通道端点底层的生成器):消费 sess.event_queue 的 web 契约事件,
    产出 SSE data 行(带 type/字段)。RunEnd 不 break(持久流),前端凭 RunStart/RunEnd 落状态。"""
    import json

    from chatweb.backend import server
    import agent.persist.paths as paths
    from agent.streaming.events import RunStart, AssistantMessage, RunEnd

    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")
    sess = server.SessionState.create(
        registry=server._registry, model_adapter=object(), tool_executor=server._tool_executor,
        config=server._config, guardrail_runner=server._guardrail_runner,
        memory_store=server._memory_store, workspace=server._workspace,
    )
    # 预填队列(模拟一个 turn 已触发)
    sess.event_queue.put_nowait(RunStart(run_id=sess.run_id))
    sess.event_queue.put_nowait(AssistantMessage(run_id=sess.run_id, uuid="u1", text="hi"))
    sess.event_queue.put_nowait(RunEnd(status="completed"))

    async def _run():
        types: list[str] = []
        async for line in server._stream_gen(sess):
            ev = json.loads(line[6:])   # 剥 "data: " 前缀
            types.append(ev["type"])
            if ev["type"] == "RunEnd":
                break   # 测试侧 break(生产流常驻)
        return types

    types = asyncio.run(_run())
    assert types == ["RunStart", "AssistantMessage", "RunEnd"]
