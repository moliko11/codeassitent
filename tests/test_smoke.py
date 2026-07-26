"""阶段3 验收烟雾测试。

用 mock ModelAdapter 跑通 agentloop 全流程，覆盖：
- 多轮 Agent Loop（running 稳态、waiting_tool 接线、终态守卫）
- tool_history 摘要写入（P1-1，状态膨胀控制）
- 状态 JSON 序列化往返（P1-2/P1-3，checkpoint 地基）
- 状态机非法转换拦截（P0-2）
- 乐观锁 CAS（P0-3）

不依赖真实 LLM API。运行（从 code/ 目录，3.12 venv）：
    python -m pytest tests/test_smoke.py -v
"""

import json
import pytest
from agent.agentloop import agentloop
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.core.errors import IllegalTransitionError
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.tools.defs import ToolCall
from agent.core.models import ModelResponse
from agent.adapters.base import BaseModelAdapter
from agent.core.messages import Message


class _ScriptedAdapter(BaseModelAdapter):
    """按脚本返回 ModelResponse 的假适配器：
    前 tool_rounds 轮返回 tool_calls，之后返回 text(final answer)。

    继承 BaseModelAdapter 以获得默认 stream_llm（退化为 call_llm + 一次性推事件），
    使流式路径对测试透明：agentloop 调 stream_llm -> 走 call_llm 脚本。
    """

    def __init__(self, tool_rounds: int):
        # 测试不依赖真实 provider 凭据；默认 stream_llm 只用 call_llm，无需它们
        super().__init__(api_key="", base_url="", model="")
        self.n = 0
        self.tool_rounds = tool_rounds

    def call_llm(self, request):
        self.n += 1
        if self.n <= self.tool_rounds:
            return ModelResponse(
                text=None,
                tool_calls=[ToolCall(
                    call_id=f"c{self.n}",
                    tool_name="nope",  # 故意未注册，触发 ToolNotFound（覆盖失败路径）
                    arguments={"q": "X" * 1000},
                )],
            )
        return ModelResponse(text="done")

    def append_assistant(self, messages, model_response):
        # 模拟真实 provider：copy + append（返回新 list），让多轮 messages 累积可测
        new_messages = list(messages)
        new_messages.append(Message(role="assistant", content=model_response.text or ""))
        return new_messages

    def append_tool_result(self, messages, result):
        new_messages = list(messages)
        new_messages.append(Message(role="tool", content=result.text or ""))
        return new_messages

    def append_tool_results(self, messages, model_response, tool_results):
        return messages  # 兼容旧接口（基类已有默认实现，此处保留原行为）


def _run_agent(tool_rounds=2) -> AgentState:
    reg = ToolRegistry()
    ctx = RuntimeContext(
        registry=reg,
        tool_executor=ToolExecutor(reg),
        model_adapter=_ScriptedAdapter(tool_rounds),
        config=AgentConfig(max_steps=5),
        state=AgentState(),
    )
    return agentloop("hi", ctx)


def test_multi_step_loop_completes():
    """多轮 tool_calls 后 final answer：status=completed，步数=tool_rounds+1。"""
    s = _run_agent(tool_rounds=2)
    assert s.status == "completed"
    assert len(s.steps) == 3  # 2 轮工具 + 1 轮 final


def test_tool_history_written_and_compact():
    """P1-1：tool_history 写入摘要，不含完整参数（状态膨胀控制）。"""
    s = _run_agent(tool_rounds=2)
    assert len(s.tool_history) == 2
    for h in s.tool_history:
        assert h.call_id in ("c1", "c2")
        assert h.tool_name == "nope"
        assert h.ok is False
        assert h.error_type == "ToolNotFound"
    # 摘要不含完整参数（1000 个 X 没泄漏到 tool_history）
    blob = json.dumps([h.__dict__ for h in s.tool_history], ensure_ascii=False)
    assert "X" * 100 not in blob


def test_state_json_roundtrip():
    """P1-2/P1-3：to_dict -> json -> from_dict 往返，关键字段一致。"""
    s = _run_agent(tool_rounds=2)
    js = json.dumps(s.to_dict())  # 不抛 TypeError 即过（P1-3）
    s2 = AgentState.from_dict(json.loads(js))
    assert s2.status == s.status
    assert s2.should_continue() == s.should_continue()
    assert s2.version == s.version  # P1-2 version 往返
    assert len(s2.tool_history) == len(s.tool_history)
    assert len(s2.steps) == len(s.steps)


def test_illegal_transition_raises():
    """P0-2：状态机非法转换抛 IllegalTransitionError（running->running 不合法）。"""
    s = AgentState()
    s.transition("running")
    with pytest.raises(IllegalTransitionError):
        s.transition("running")  # running 后继不含 running


def test_try_apply_cas():
    """P0-3：try_apply 乐观锁，版本匹配才应用，冲突拒绝。"""
    s = AgentState()
    s.transition("running")
    v = s.version

    def to_waiting(st):
        st.transition("waiting_tool")

    assert s.try_apply(to_waiting, v) is True      # 版本匹配，成功
    assert s.try_apply(to_waiting, 999) is False   # 版本不匹配，拒绝
