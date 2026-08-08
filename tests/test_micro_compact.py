"""阶段 6 步骤 4 测试:MicroCompact(第3层,低损清老工具结果)。

不依赖真实 LLM。运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_micro_compact.py -v
"""
from agent.context.micro_compact import micro_compact, CLEARED_MESSAGE
from agent.context.budget import PERSISTED_TAG
from agent.core.messages import Message


def _tool_msg(call_id: str, text: str) -> Message:
    return Message(role="tool", content=text, meta={"tool_call_id": call_id})


def _user_msg(text: str) -> Message:
    return Message(role="user", content=text)


def test_keeps_recent_k_tool_results():
    """超过 keep_recent 的老 tool_result content 被清成占位,最近 K 个保留。"""
    msgs = [
        _user_msg("q1"), _tool_msg("c1", "old1"),
        _user_msg("q2"), _tool_msg("c2", "old2"),
        _user_msg("q3"), _tool_msg("c3", "old3"),
        _user_msg("q4"), _tool_msg("c4", "recent1"),
    ]
    out = micro_compact(msgs, keep_recent=2)
    # 最近 2 个(c3, c4)保留原文;更早的 c1, c2 被清
    cleared_texts = [m.content for m in out if m.role == "tool" and m.content == CLEARED_MESSAGE]
    assert len(cleared_texts) == 2  # c1, c2
    # c3, c4 原文保留
    tool_texts = [m.content for m in out if m.role == "tool"]
    assert "old3" in tool_texts and "recent1" in tool_texts


def test_under_keep_recent_no_change():
    """tool_result 数 <= keep_recent,不动。"""
    msgs = [_user_msg("q"), _tool_msg("c1", "x")]
    out = micro_compact(msgs, keep_recent=3)
    assert out == msgs


def test_persisted_reference_not_cleared():
    """步3落盘的引用(persisted-output)不清--模型可 Read 回。"""
    ref = PERSISTED_TAG + "\npath: x\ntail\n</persisted-output>"
    msgs = [_tool_msg("c1", ref), _tool_msg("c2", "recent")]
    out = micro_compact(msgs, keep_recent=1)
    # c1 是引用,即使老也保留(不清成 CLEARED_MESSAGE)
    c1_out = [m for m in out if m.meta.get("tool_call_id") == "c1"][0]
    assert c1_out.content == ref


def test_original_message_not_mutated():
    """不改原始 Message 对象。"""
    msgs = [_tool_msg("c1", "old"), _tool_msg("c2", "recent")]
    micro_compact(msgs, keep_recent=1)
    assert msgs[0].content == "old"  # 原对象没被改


def test_non_tool_messages_passthrough():
    """非 tool 消息不受影响。"""
    msgs = [_user_msg("a"), Message(role="assistant", content="b")]
    out = micro_compact(msgs, keep_recent=3)
    assert out == msgs


def _six_tool_msgs_with_assistant(last_assistant_ts):
    """6 条工具结果(超 keep_recent=5)+ 首尾 assistant(尾带指定 ts)。"""
    return [
        Message(role="assistant", content="a", meta={"ts": last_assistant_ts}),
        _tool_msg("c1", "old1"), _tool_msg("c2", "old2"),
        _tool_msg("c3", "r3"), _tool_msg("c4", "r4"),
        _tool_msg("c5", "r5"), _tool_msg("c6", "r6"),
        Message(role="assistant", content="b", meta={"ts": last_assistant_ts}),
    ]


def test_time_gate_skips_recent_session():
    """对齐 CC gapThresholdMinutes:距最后一条 assistant < 阈值(短会话)时不清老工具结果。"""
    import time
    now = time.time()
    msgs = _six_tool_msgs_with_assistant(now - 10)   # 10 秒前(< 60min)
    out = micro_compact(msgs, keep_recent=5, gap_threshold_minutes=60)
    assert out == msgs   # 一条都不清(含 c1 老结果)


def test_time_gate_clears_after_threshold():
    """对齐 CC:距最后一条 assistant >= 阈值(2 小时)才清,且只清超过 keepRecent 的老的。"""
    import time
    now = time.time()
    msgs = _six_tool_msgs_with_assistant(now - 7200)   # 2 小时前(>= 60min)
    out = micro_compact(msgs, keep_recent=5, gap_threshold_minutes=60)
    texts = [m.content for m in out if m.role == "tool"]
    assert "old1" not in texts    # c1 被清(6 条超 keep_recent 5)
    assert "old2" in texts        # c2 是最近 5 条之一,保留
    assert "r6" in texts          # 最近 5 条都保留


def test_time_gate_no_timestamp_skips():
    """对齐 CC:最后一条 assistant 无时间戳(测试 mock/老数据)-> 无法判定,不清。"""
    msgs = [
        Message(role="assistant", content="a"),   # 无 meta.ts
        _tool_msg("c1", "old1"), _tool_msg("c2", "old2"),
        _tool_msg("c3", "r3"), _tool_msg("c4", "r4"),
        _tool_msg("c5", "r5"), _tool_msg("c6", "r6"),
        Message(role="assistant", content="b"),   # 无 meta.ts
    ]
    out = micro_compact(msgs, keep_recent=5, gap_threshold_minutes=60)
    assert out == msgs