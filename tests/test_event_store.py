"""EventStore:前端事件流(web 契约)落盘测试(2026-08-08)。

验证:
- EventStore 只写 web 契约事件(is_web_event)到 events.jsonl,每条带 ts/type/字段;
  低层 delta 与机制事件不落
- 同一 run 跨多个 store append(REPL/web 多 turn 场景,复用同一个 events.jsonl,不覆盖)
- 走 agentloop(persist=True, mock adapter)端到端:run/ 落盘 events.jsonl,含
  RunStart/AssistantMessage/ToolResultMessage/RunEnd,形状 = server._event_to_dict
  (type + 事件字段,前端 eventReducer 可直接重放);机制事件不落
- 惰性:只有非 web 事件的 run 不建空 events.jsonl
is_web_event 白名单本身在 test_events_messages 验证(契约单点)。
不依赖真实 LLM(同 test_events_messages 的 _ToolAdapter 模式)。
运行(从 code/,3.12 venv): python -m pytest tests/test_event_store.py -v
"""
import asyncio
import json

import pytest

import agent.persist.paths as paths
from agent.persist.store import read_events
from agent.agentloop import agentloop
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.core.messages import Message
from agent.core.models import ModelResponse, TokenUsage
from agent.adapters.base import BaseModelAdapter
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.tools.defs import ToolCall, Tool, ToolSpec
from agent.streaming.sink import NullSink
from agent.streaming.event_store import EventStore
from agent.streaming.events import (
    RunStart, RunEnd, AssistantMessage, ToolResultMessage, StepStart, TextDelta,
)


@pytest.fixture(autouse=True)
def _tmp_persist_root(tmp_path, monkeypatch):
    """PERSIST_ROOT 指到 tmp_path,测试落盘不污染 code/persist(同 test_persist)。"""
    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")


def _read_events(run_id) -> list[dict]:
    p = paths.PERSIST_ROOT / run_id / "events.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


class _ToolAdapter(BaseModelAdapter):
    """前 rounds 轮返回工具调用(带 usage),之后返回 final answer(同 test_events_messages)。"""

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
                usage=TokenUsage(input_tokens=100 + self.n, output_tokens=50, total_tokens=150 + self.n),
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


def test_event_store_writes_only_web_events(tmp_path):
    """EventStore 只写 web 契约事件;每条带 ts/type/字段;低层 delta 与机制事件不落。"""
    run_id = "es-unit"
    store = EventStore(run_id, path=str(tmp_path / "events.jsonl"))
    try:
        store.emit(RunStart(run_id=run_id))
        store.emit(AssistantMessage(
            run_id=run_id, uuid="u1", text="hi",
            tool_calls=(dict(call_id="c1", tool_name="read", arguments={"p": "x"}),),
            usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        ))
        store.emit(ToolResultMessage(run_id=run_id, uuid="u2", call_id="c1",
                                     tool_name="read", ok=True, summary="ok", elapsed_ms=1.2))
        store.emit(TextDelta(text="x"))          # 低层 delta:web 吞,不落
        store.emit(StepStart(step_index=0))      # 机制事件:web 吞,不落
        store.emit(RunEnd(status="completed", usage={"input_tokens": 10, "output_tokens": 5}))
    finally:
        store.close()

    lines = [json.loads(l) for l in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["type"] for l in lines] == ["RunStart", "AssistantMessage", "ToolResultMessage", "RunEnd"]

    am = lines[1]
    assert am["run_id"] == run_id and am["text"] == "hi" and am["uuid"] == "u1"
    assert am["tool_calls"][0]["tool_name"] == "read"          # tuple -> list(前端 reducer 兼容)
    assert am["tool_calls"][0]["call_id"] == "c1"
    assert am["usage"]["input_tokens"] == 10                   # TokenUsage -> dict
    assert am["ts"] > 0                                        # 墙钟

    tr = lines[2]
    assert tr["call_id"] == "c1" and tr["ok"] is True and tr["elapsed_ms"] == 1.2
    assert tr["summary"] == "ok"

    assert lines[3]["status"] == "completed"                   # RunEnd 带聚合 usage
    assert lines[3]["usage"]["input_tokens"] == 10


def test_event_store_appends_across_stores(tmp_path):
    """同一 run 跨多个 store(REPL/web 多 turn)append 到同一 events.jsonl,不覆盖。"""
    run_id = "es-multiturn"
    s1 = EventStore(run_id)
    s1.emit(RunStart(run_id=run_id))
    s1.emit(AssistantMessage(run_id=run_id, uuid="a1", text="first"))
    s1.close()
    s2 = EventStore(run_id)
    s2.emit(AssistantMessage(run_id=run_id, uuid="a2", text="second"))
    s2.emit(RunEnd(status="completed"))
    s2.close()

    lines = _read_events(run_id)
    assert [l["type"] for l in lines] == ["RunStart", "AssistantMessage", "AssistantMessage", "RunEnd"]
    assert lines[1]["text"] == "first"
    assert lines[2]["text"] == "second"
    assert lines[3]["status"] == "completed"


def test_event_store_lazy_no_empty_file(tmp_path):
    """惰性:只有非 web 事件的 run 不建空 events.jsonl。"""
    store = EventStore("es-lazy", path=str(tmp_path / "events.jsonl"))
    try:
        store.emit(TextDelta(text="x"))
        store.emit(StepStart(step_index=0))
    finally:
        store.close()
    assert not (tmp_path / "events.jsonl").exists()


def test_read_events_from_disk(tmp_path):
    """read_events 读回 events.jsonl(给前端重放);无 events.jsonl 返回 None;损坏行跳过。"""
    run_id = "es-read"
    store = EventStore(run_id)
    try:
        store.emit(RunStart(run_id=run_id))
        store.emit(AssistantMessage(run_id=run_id, uuid="u1", text="hi", thinking="想"))
        store.emit(TextDelta(text="x"))   # 非 web,不落
    finally:
        store.close()
    events = read_events(run_id)
    assert events is not None
    assert [e["type"] for e in events] == ["RunStart", "AssistantMessage"]
    assert events[1]["text"] == "hi" and events[1]["thinking"] == "想"   # thinking 随事件落盘,恢复不丢
    assert read_events("es-no-such-run") is None                         # 无 events.jsonl(老 run)-> None

    # 损坏行跳过(同 read_transcript 容错)
    from agent.persist.paths import run_dir
    with open(run_dir("es-read") / "events.jsonl", "a", encoding="utf-8") as f:
        f.write("{bad json}\n")
    events2 = read_events(run_id)
    assert [e["type"] for e in events2] == ["RunStart", "AssistantMessage"]


def test_agentloop_persist_writes_events_jsonl(tmp_path):
    """端到端:agentloop(persist=True, mock adapter)在 run/ 落盘 events.jsonl(web 契约事件)。
    形状 = server._event_to_dict(type + 字段),前端 eventReducer 可直接重放。"""
    reg = ToolRegistry()
    reg.register(Tool(tool_spec=ToolSpec(name="hello", description="", input_schema={}),
                      handler=lambda q="": "hi"))
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_ToolAdapter(1),
        config=AgentConfig(max_steps=5),
        state=AgentState(),
        sink=NullSink(),
        persist=True,
    )
    state = asyncio.run(agentloop("hi", ctx))

    p = paths.PERSIST_ROOT / state.run_id / "events.jsonl"
    assert p.exists(), "persist 的 run 必须落盘前端事件流 events.jsonl"
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    types = [l["type"] for l in lines]

    assert "RunStart" in types and "RunEnd" in types
    assert types.count("AssistantMessage") == 2     # 1 工具轮 + 1 final
    assert types.count("ToolResultMessage") == 1
    assert "StepStart" not in types and "StepEnd" not in types   # 机制事件不落

    # 工具轮 AssistantMessage 带完整 tool_calls/usage(前端建卡 + 显示 token)
    am = next(l for l in lines if l["type"] == "AssistantMessage" and l["text"] == "step1")
    assert am["tool_calls"][0]["tool_name"] == "hello"
    assert am["tool_calls"][0]["call_id"] == "c1"
    assert am["usage"]["input_tokens"] == 101
    # RunEnd 带整轮聚合 usage(前端 turn 结束总账)
    end = next(l for l in lines if l["type"] == "RunEnd")
    assert end["usage"]["total_tokens"] == 101 + 50 + 300 + 100   # 151 + 400 = 551
