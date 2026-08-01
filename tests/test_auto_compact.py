"""阶段 6 步骤 5 测试:AutoCompact(第5层,有损摘要兜底)。

不依赖真实 LLM(用 mock summarizer + mock adapter)。运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_auto_compact.py -v
"""
import asyncio

from agent.context.auto_compact import auto_compact, make_summarizer
from agent.context import ContextBuilder
from agent.core.messages import Message
from agent.core.state import AgentState
from agent.adapters.base import BaseModelAdapter
from agent.core.models import ModelResponse


def _user_msg(t): return Message(role="user", content=t)
def _asst_msg(t): return Message(role="assistant", content=t)


def _const_summarizer(text):
    """把常量文本包成 async summarizer(auto_compact 要求 summarizer 可 await)。"""
    async def _s(messages):
        return text
    return _s


def test_auto_compact_summarizes_old_keeps_recent():
    """老消息被摘要成一条 summary,尾部 keep_recent_turns 条保留。"""
    msgs = [
        Message(role="system", content="SYS"),
        _user_msg("old1"), _asst_msg("a1"),
        _user_msg("old2"), _asst_msg("a2"),
        _user_msg("recent1"), _asst_msg("ra1"),
    ]
    out = asyncio.run(auto_compact(msgs, summarizer=_const_summarizer("MOCK_SUMMARY"), keep_recent_turns=2))
    # system 保留在最前
    assert out[0].role == "system" and out[0].content == "SYS"
    # 第二条是 summary
    assert out[1].role == "system" and "MOCK_SUMMARY" in out[1].content
    # 尾部保留 2 条(recent1, ra1)
    assert out[-2].content == "recent1" and out[-1].content == "ra1"
    # 摘要后比原来短
    assert len(out) < len(msgs)


def test_auto_compact_nothing_to_summarize():
    """消息数 <= keep_recent_turns,不动。"""
    msgs = [Message(role="system", content="SYS"), _user_msg("only")]
    out = asyncio.run(auto_compact(msgs, summarizer=_const_summarizer("X"), keep_recent_turns=4))
    assert out == msgs


def test_make_summarizer_calls_adapter():
    """make_summarizer 用 adapter.call_llm 摘要,返回 resp.text。"""
    class _SummAdapter(BaseModelAdapter):
        def __init__(self): super().__init__("", "", "")
        async def call_llm(self, req):
            assert req.messages[0].role == "system"  # 摘要 system prompt 在前
            return ModelResponse(text="summary from llm")
        def append_assistant(self, m, r): return m
        def append_tool_result(self, m, r): return m
    summ = make_summarizer(_SummAdapter())
    assert asyncio.run(summ([_user_msg("hi")])) == "summary from llm"


def test_make_summarizer_swallows_failure():
    """adapter 抛异常时返回占位,不传播。"""
    class _BadAdapter(BaseModelAdapter):
        def __init__(self): super().__init__("", "", "")
        async def call_llm(self, req): raise RuntimeError("boom")
        def append_assistant(self, m, r): return m
        def append_tool_result(self, m, r): return m
    summ = make_summarizer(_BadAdapter())
    assert "摘要失败" in asyncio.run(summ([_user_msg("hi")]))


def test_build_triggers_auto_compact_when_over_budget():
    """集成:小 budget + mock summarizer,build 触发 AutoCompact。"""
    called = []
    async def summ(m):
        called.append(len(m))
        return "压缩摘要"
    # 塞足够长的历史让 token 超 budget=20
    state = AgentState()
    state.messages.append(Message(role="system", content="SYS"))
    for i in range(10):
        state.messages.append(_user_msg("问题" * 20))
        state.messages.append(_asst_msg("回答" * 20))
    builder = ContextBuilder(context_budget=20, summarizer=summ, keep_recent_turns=2)
    result = asyncio.run(builder.build(state))
    assert called  # summarizer 被调过
    assert any("压缩摘要" in str(m.content) for m in result.messages)  # summary 进了 messages
    # 摘要后 token 比摘要前(state.messages 原始)小
    from agent.context import count_message_tokens
    assert result.token_count < count_message_tokens(list(state.messages))