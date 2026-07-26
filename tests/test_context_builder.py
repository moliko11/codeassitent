"""阶段 6 地基测试：ContextBuilder 透传 + token 计数 + budget 检查。

不依赖真实 LLM。运行(从 code/ 目录，3.12 venv)：
    python -m pytest tests/test_context_builder.py -v
"""
from agent.context import ContextBuilder, count_message_tokens, estimate_text_tokens
from agent.core.messages import Message
from agent.core.state import AgentState


def _state_with_messages(n: int) -> AgentState:
    """造一个有 n 条 user 消息的 state，每条 50 个汉字。"""
    s = AgentState()
    for _ in range(n):
        s.messages.append(Message(role="user", content="汉" * 50))
    return s


def test_estimate_text_tokens_basic():
    # 纯英文 ~4 字符/token；纯中文 ~1.5 字符/token
    assert estimate_text_tokens("hello world") > 0
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens(None) == 0
    # 50 个汉字约 33 token +1 边界
    assert 30 <= estimate_text_tokens("汉" * 50) <= 40


def test_count_message_tokens_grows_with_messages():
    s1 = _state_with_messages(1)
    s3 = _state_with_messages(3)
    assert count_message_tokens(s3.messages) > count_message_tokens(s1.messages)


def test_builder_passthrough_does_not_mutate_state():
    """透传：build 返回的 messages 与 state.messages 内容一致，且不改原始 list。"""
    s = _state_with_messages(3)
    builder = ContextBuilder(context_budget=None)
    result = builder.build(s)
    assert len(result.messages) == 3
    assert result.token_count > 0
    assert result.over_budget is False  # budget=None 不限
    # 原始 state.messages 未被改动(长度仍是 3)
    assert len(s.messages) == 3


def test_builder_over_budget_flags_but_does_not_trim():
    """超 budget：over_budget=True，但本阶段不裁剪，messages 仍全量透传。"""
    s = _state_with_messages(10)  # 10 条 50 汉字 -> 远超 50
    warned = []
    builder = ContextBuilder(
        context_budget=50,  # 故意设很小
        warn_sink=lambda m: warned.append(m),
    )
    result = builder.build(s)
    assert result.over_budget is True
    assert len(result.messages) == 10  # 没裁剪，仍 10 条
    assert len(warned) == 1 and "over budget" in warned[0]


def test_builder_injected_via_runtimecontext_runs_agentloop():
    """集成：注入自定义 builder，跑通 agentloop 不崩，行为不变。"""
    from agent.agentloop import agentloop
    from agent.runtime import RuntimeContext
    from agent.config.config import AgentConfig
    from agent.tools.registry import ToolRegistry, ToolExecutor
    from agent.adapters.base import BaseModelAdapter
    from agent.core.models import ModelResponse
    from agent.tools.defs import ToolCall

    class _FinalAdapter(BaseModelAdapter):
        """只回一次 final answer 的最简 adapter。"""
        def __init__(self):
            super().__init__(api_key="", base_url="", model="")
        def call_llm(self, request):
            return ModelResponse(text="ok")
        def append_assistant(self, messages, resp):
            return [*messages, Message(role="assistant", content=resp.text or "")]
        def append_tool_result(self, messages, result):
            return [*messages, Message(role="tool", content=result.text or "")]

    reg = ToolRegistry()
    builder = ContextBuilder(context_budget=1000)
    ctx = RuntimeContext(
        registry=reg,
        tool_executor=ToolExecutor(reg),
        model_adapter=_FinalAdapter(),
        config=AgentConfig(max_steps=3),
        state=AgentState(),
        context_builder=builder,  # 注入
    )
    s = agentloop("hi", ctx)
    assert s.status == "completed"