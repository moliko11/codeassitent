"""Phase 1(web 前端完善)验收测试。对齐 fullstack-dev-plan §1.1/§1.2/§1.3:
- §1.1 会话标题:_first_user_title 推导(跳系统注入+截断)、_write_run_meta 显式 title、
  store.set_run_title、_scan_transcript_tail 兜底 title
- §1.2/§1.3 历史恢复:_transcript_to_messages 恢复 thinking/usage/error_type/error_message

纯函数部分不依赖真实 LLM(同 test_smoke 模式);_transcript_to_messages 在 server.py,
import 需 .env 的 API key —— 无 key 机器跳过(requires_server)。运行(从 code/,3.12 venv):
    python -m pytest tests/test_phase1_web.py -v
"""
import json
import types

import pytest

import agent.persist.paths as paths
from agent.agentloop import _first_user_title, _write_run_meta
from agent.core.messages import Message
from agent.core.models import ModelResponse, TokenUsage
from agent.persist.persister import Persister
from agent.persist.store import _scan_transcript_tail, set_run_title
from agent.tools.defs import ToolCall, ToolResult


@pytest.fixture(autouse=True)
def _tmp_persist_root(tmp_path, monkeypatch):
    """PERSIST_ROOT 指到 tmp_path,测试落盘不污染 code/persist/runs(同 test_web)。"""
    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")


def _mkreport():
    """_write_run_meta 需要的 MetricsCollector 结果形状。"""
    return types.SimpleNamespace(duration_ms=1000, token_input=1, token_output=2,
                                 token_total=3, token_cached=0, step_count=1,
                                 tool_count=1, tool_success_rate=1.0)


# ─────────────────────── §1.1 会话标题 ───────────────────────

def test_first_user_title_skips_system_injected():
    """首条真实 user 作标题;跳过 [系统提示]/[task-notification] 等系统注入前缀。"""
    msgs = [
        Message(role="system", content="SYS"),
        Message(role="user", content="[系统提示] 环境信息"),
        Message(role="user", content="[task-notification] 后台任务完成"),
        Message(role="user", content="帮我写个快排"),
    ]
    assert _first_user_title(msgs) == "帮我写个快排"


def test_first_user_title_truncates():
    """超 30 字截断加 …(31 字符)。"""
    msgs = [Message(role="user", content="这是一条很长很长的用户消息超过三十个字符看它到底会不会被截断掉呢")]
    t = _first_user_title(msgs)
    assert len(t) == 31 and t.endswith("…")


def test_first_user_title_skips_non_str_content():
    """dict content(工具轮 user 回灌)跳过,不崩溃。"""
    msgs = [Message(role="user", content={"type": "function_call_output", "call_id": "x"})]
    assert _first_user_title(msgs) == ""


def test_first_user_title_empty_when_no_user():
    assert _first_user_title([Message(role="system", content="SYS")]) == ""


def test_write_run_meta_title_derived_default():
    """title 缺省时从首条 user 推导落盘(web server 首轮调)。"""
    state = types.SimpleNamespace(run_id="r-title", status="completed",
                                  messages=[Message(role="user", content="推导标题测试")])
    _write_run_meta(state, _mkreport(), model="m")
    meta = json.loads((paths.PERSIST_ROOT / "r-title" / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "推导标题测试"


def test_write_run_meta_title_explicit_wins():
    """显式 title(用户重命名过)优先,不被推导覆盖。"""
    state = types.SimpleNamespace(run_id="r-title2", status="completed",
                                  messages=[Message(role="user", content="首轮原题")])
    _write_run_meta(state, _mkreport(), model="m", title="用户自定义")
    meta = json.loads((paths.PERSIST_ROOT / "r-title2" / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "用户自定义"


def test_set_run_title_updates_meta():
    """重命名:覆写 run_meta 的 title。"""
    state = types.SimpleNamespace(run_id="r-ren", status="completed",
                                  messages=[Message(role="user", content="旧题")])
    _write_run_meta(state, _mkreport(), model="m")
    set_run_title("r-ren", "新名字")
    meta = json.loads((paths.PERSIST_ROOT / "r-ren" / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "新名字"


def test_set_run_title_empty_noop():
    """空标题 no-op,不改原 title。"""
    state = types.SimpleNamespace(run_id="r-ren2", status="completed",
                                  messages=[Message(role="user", content="旧题")])
    _write_run_meta(state, _mkreport(), model="m")
    set_run_title("r-ren2", "")
    meta = json.loads((paths.PERSIST_ROOT / "r-ren2" / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "旧题"


def test_scan_transcript_tail_title_fallback():
    """无 run_meta 侧车时,扫 transcript 首条真实 user 作 title(崩溃 run 兜底)。"""
    p = Persister("r-tail")
    p.log_user("[系统提示] 环境信息")                       # 跳过
    p.log_user("兜底标题的第一条真实用户消息它比较长要超过三十个字符好验证截断逻辑是否正常工作")
    p.log_run_end("complete")
    p.close()
    meta = _scan_transcript_tail("r-tail")
    assert meta["title"].startswith("兜底标题的第一条真实用户消息它比较长要超过三") and meta["title"].endswith("…")
    assert meta["status"] == "complete"


# ─────────────────── §1.2/§1.3 历史恢复(server 依赖)───────────────────

try:
    from chatweb.backend.server import _transcript_to_messages
    _HAVE_SERVER = True
except Exception:
    _HAVE_SERVER = False

requires_server = pytest.mark.skipif(not _HAVE_SERVER,
                                     reason="chatweb.backend.server import 需 .env 的 API key")


def _seed_transcript(run_id, *, with_thinking=True, with_usage=True):
    """造一个带 thinking/usage/tool_calls + 成功/失败工具结果的 transcript。"""
    p = Persister(run_id)
    p.log_user("[系统提示] env")                          # 应被跳过
    p.log_user("真实用户消息")
    mr = ModelResponse(
        text="我来看看",
        thinking="先想一下再动手" if with_thinking else None,
        tool_calls=[ToolCall(call_id="c1", tool_name="read", arguments={"path": "a.txt"}),
                    ToolCall(call_id="c2", tool_name="bash", arguments={"command": "ls"})],
        usage=TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30) if with_usage else None,
    )
    p.log_assistant(mr)
    p.log_tool_result(ToolResult(call_id="c1", tool_name="read", ok=False,
                                 error={"type": "ToolExecutionError", "message": "文件不存在",
                                        "retryable": True}, text="错误了"))
    p.log_tool_result(ToolResult(call_id="c2", tool_name="bash", ok=True, text="file list"))
    p.close()


@requires_server
def test_transcript_recovers_thinking_usage():
    """§1.2:assistant 恢复 thinking + usage(不再是流式临时)。"""
    _seed_transcript("r-recover")
    msgs = _transcript_to_messages("r-recover")
    a = next(m for m in msgs if m["role"] == "assistant")
    assert a["thinking"] == "先想一下再动手"
    assert a["usage"] == {"input_tokens": 10, "output_tokens": 20,
                          "total_tokens": 30, "cached_tokens": 0}


@requires_server
def test_transcript_recovers_tool_error_fields():
    """§1.3:失败工具结果带 errorType/errorMessage;成功的不带。"""
    _seed_transcript("r-recover2")
    msgs = _transcript_to_messages("r-recover2")
    a = next(m for m in msgs if m["role"] == "assistant")
    tcs = {tc["callId"]: tc for tc in a["toolCalls"]}
    assert tcs["c1"]["phase"] == "error"
    assert tcs["c1"]["errorType"] == "ToolExecutionError"
    assert tcs["c1"]["errorMessage"] == "文件不存在"
    assert tcs["c2"]["phase"] == "done" and tcs["c2"]["ok"] is True
    assert "errorType" not in tcs["c2"]


@requires_server
def test_transcript_skips_system_injected_user():
    """历史恢复也跳系统注入的 user 消息,只留真实用户消息。"""
    _seed_transcript("r-recover3")
    msgs = _transcript_to_messages("r-recover3")
    users = [m for m in msgs if m["role"] == "user"]
    assert len(users) == 1 and users[0]["content"] == "真实用户消息"


@requires_server
def test_transcript_handles_no_thinking_usage():
    """老 transcript(无 thinking/usage 字段)不崩溃,缺省不填。"""
    _seed_transcript("r-recover4", with_thinking=False, with_usage=False)
    msgs = _transcript_to_messages("r-recover4")
    a = next(m for m in msgs if m["role"] == "assistant")
    assert "thinking" not in a and "usage" not in a


@requires_server
def test_messages_endpoint_prefers_events_source():
    """历史恢复端点:有 events.jsonl -> source=events(前端重放,含 thinking,恢复=直播画面);
    只有 transcript(老 run,无 events.jsonl)-> 退化 source=transcript(直接可用)。"""
    from fastapi.testclient import TestClient
    from chatweb.backend import server
    from agent.streaming.event_store import EventStore
    from agent.streaming.events import RunStart, AssistantMessage, RunEnd

    client = TestClient(server.app)

    # 新 run:events.jsonl 优先(source=events,前端过 eventReducer 重放)
    store = EventStore("r-evt")
    try:
        store.emit(RunStart(run_id="r-evt"))
        store.emit(AssistantMessage(run_id="r-evt", uuid="u1", text="hi", thinking="先想"))
        store.emit(RunEnd(status="completed"))
    finally:
        store.close()
    data = client.get("/sessions/r-evt/messages").json()
    assert data["source"] == "events"
    assert [e["type"] for e in data["events"]] == ["RunStart", "AssistantMessage", "RunEnd"]
    assert data["events"][1]["thinking"] == "先想"   # thinking 随事件落盘,恢复不丢

    # 老 run:只有 transcript -> 退化 source=transcript(messages 直接可用)
    _seed_transcript("r-evt-old")
    data2 = client.get("/sessions/r-evt-old/messages").json()
    assert data2["source"] == "transcript"
    assert any(m["role"] == "assistant" for m in data2["messages"])
