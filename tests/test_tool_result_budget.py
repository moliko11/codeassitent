"""阶段 6 步骤 3 测试:ToolResultBudget(第1层,无损落盘)。

不依赖真实 LLM。运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_tool_result_budget.py -v
"""
from agent.context.budget import (
    apply_tool_result_budget,
    PERSIST_THRESHOLD_CHARS,
    PERSISTED_TAG,
)
from agent.core.messages import Message


def _tool_msg(call_id: str, text: str) -> Message:
    """构造结构化 tool 结果消息(对齐 openai_compat.append_tool_result:content=文本,meta 关联)。"""
    return Message(
        role="tool",
        content=text,
        meta={"tool_call_id": call_id},
    )


def test_small_result_not_persisted(tmp_path, monkeypatch):
    """小结果(<= 阈值)原样返回,不落盘。"""
    monkeypatch.setattr("agent.persist.paths.PERSIST_ROOT", tmp_path / "runs")
    msgs = [_tool_msg("c1", "small")]
    out = apply_tool_result_budget(msgs, "run-x")
    assert out[0].content == "small"
    assert not (tmp_path / "runs" / "run-x" / "tool-results" / "c1.txt").exists()


def test_large_result_persisted_and_replaced(tmp_path, monkeypatch):
    """大结果(> 阈值)落盘,content 换成引用,全文写磁盘,call_id 保留。"""
    monkeypatch.setattr("agent.persist.paths.PERSIST_ROOT", tmp_path / "runs")
    big = "X" * (PERSIST_THRESHOLD_CHARS + 100)
    msgs = [_tool_msg("c1", big)]
    out = apply_tool_result_budget(msgs, "run-x")

    ref = out[0].content
    assert PERSISTED_TAG in ref               # 是引用
    assert "c1.txt" in ref                    # 引用里带路径
    assert "X" * 100 in ref                   # 预览含前 N 字符
    assert out[0].meta["tool_call_id"] == "c1"   # call_id 保留

    # 全文落盘且内容完整
    f = tmp_path / "runs" / "run-x" / "tool-results" / "c1.txt"
    assert f.exists()
    assert f.read_text(encoding="utf-8") == big


def test_original_message_not_mutated(tmp_path, monkeypatch):
    """不改原始 Message 对象(state.messages 保持完整)。"""
    monkeypatch.setattr("agent.persist.paths.PERSIST_ROOT", tmp_path / "runs")
    big = "Y" * (PERSIST_THRESHOLD_CHARS + 10)
    orig = _tool_msg("c1", big)
    apply_tool_result_budget([orig], "run-x")
    assert orig.content == big     # 原对象没被改


def test_idempotent(tmp_path, monkeypatch):
    """调两次结果一致(文件已存在则跳过)。"""
    monkeypatch.setattr("agent.persist.paths.PERSIST_ROOT", tmp_path / "runs")
    big = "Z" * (PERSIST_THRESHOLD_CHARS + 10)
    msgs = [_tool_msg("c1", big)]
    out1 = apply_tool_result_budget(msgs, "run-x")
    out2 = apply_tool_result_budget(msgs, "run-x")
    assert out1[0].content == out2[0].content


def test_non_tool_messages_passthrough(tmp_path, monkeypatch):
    """非 tool 消息原样透传。"""
    monkeypatch.setattr("agent.persist.paths.PERSIST_ROOT", tmp_path / "runs")
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ]
    out = apply_tool_result_budget(msgs, "run-x")
    assert out == msgs