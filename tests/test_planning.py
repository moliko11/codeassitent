"""阶段 7 Planning/ReAct/Workflow 验收测试。

覆盖 stage7-plan §4 的测试矩阵:
- ReAct 三段 view property(任务1)
- plan_execute 跑通(任务2/3)
- Critic 防漂移 replan(任务4/5)
- TodoWrite nudge(任务2')
- workflow DAG mode(任务7)
- 推理可见性 expose_reasoning(任务6)

不依赖真实 LLM,用 _PlanExecuteAdapter mock(按 request 首条 system 内容分流返回 plan/critique/子任务响应)。
运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_planning.py -v
"""

import io
import json
import pytest

from agent.agentloop import agentloop
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.tools.defs import ToolCall
from agent.core.models import ModelResponse
from agent.adapters.base import BaseModelAdapter
from agent.core.messages import Message
from agent.streaming.printer import StreamingPrinter
from agent.streaming.events import TextDelta, ThinkingDelta


class _PlanExecuteAdapter(BaseModelAdapter):
    """plan_execute 测试 mock:按 request 首条 system 内容分流。

    - PLAN_PROMPT   -> 返回 plan JSON(N 步)
    - CRITIC_PROMPT -> 返回 critique JSON(passed/needs_replan 可控)
    - 其他(_run_steps 子任务,首条是 current_plan_step 注入的 system) -> 返回 final text(FINISH)

    继承 BaseModelAdapter 获得默认 stream_llm(退化为 call_llm + 推事件),
    使 _run_steps 的流式路径对测试透明。
    """

    def __init__(self, plan_steps=2, critic_needs_replan=False, critic_passed=True):
        super().__init__("", "", "")
        self.plan_steps = plan_steps
        self.critic_needs_replan = critic_needs_replan
        self.critic_passed = critic_passed
        self.plan_calls = 0
        self.critic_calls = 0
        self.step_calls = 0

    def call_llm(self, request):
        from agent.prompts import PLAN_PROMPT, CRITIC_PROMPT
        first = request.messages[0] if request.messages else None
        sys_content = first.content if (
            first and first.role == "system" and isinstance(first.content, str)
        ) else ""
        if sys_content == PLAN_PROMPT:
            self.plan_calls += 1
            return ModelResponse(text=json.dumps({"steps": [
                {"content": f"子任务{i+1}", "active_form": f"执行子任务{i+1}"}
                for i in range(self.plan_steps)
            ]}, ensure_ascii=False))
        if sys_content == CRITIC_PROMPT:
            self.critic_calls += 1
            return ModelResponse(text=json.dumps({
                "passed": self.critic_passed,
                "reason": "test",
                "needs_replan": self.critic_needs_replan,
            }, ensure_ascii=False))
        # 否则:_run_steps 子任务 -> 返回 final text(直接 FINISH,subtask 不 complete)
        self.step_calls += 1
        return ModelResponse(text=f"子任务{self.step_calls}完成")

    def append_assistant(self, messages, model_response):
        new = list(messages)
        new.append(Message(role="assistant", content=model_response.text or ""))
        return new

    def append_tool_result(self, messages, result):
        new = list(messages)
        new.append(Message(role="tool", content=result.text or ""))
        return new


# ─────────────────── 任务 1:ReAct view property ───────────────────

def test_react_view_properties():
    """AgentStep.thought/actions/observations 正确映射现有字段;None 兜底返回 ''。"""
    from agent.core.state import AgentStep
    step = AgentStep(index=0, model_response=ModelResponse(text="我在思考"))
    step.tool_calls = [ToolCall(call_id="c1", tool_name="t", arguments={})]
    step.tool_results = []
    assert step.thought == "我在思考"
    assert step.actions is step.tool_calls
    assert step.observations is step.tool_results
    # model_response 为 None(resume 中途/纯工具轮)
    s2 = AgentStep(index=1)
    assert s2.thought == ""
    # text 为 None(纯 tool_call 轮)
    s3 = AgentStep(index=2, model_response=ModelResponse(text=None))
    assert s3.thought == ""


# ─────────────────── 任务 2/3:plan_execute 跑通 ───────────────────

def test_plan_execute_runs_steps():
    """mock Planner 返回 2 步 Plan -> Executor 调 2 次 _run_steps(subtask) -> completed。"""
    adapter = _PlanExecuteAdapter(plan_steps=2)
    reg = ToolRegistry()
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=adapter,
        config=AgentConfig(mode="plan_execute", max_steps=5, critic_enabled=False),
        state=AgentState(max_steps=5),
    )
    state = agentloop("完成某任务", ctx)
    assert state.status == "completed"
    assert adapter.plan_calls == 1   # Planner 调一次产 Plan
    assert adapter.step_calls == 2   # 2 个 plan step 各跑一次 _run_steps


# ─────────────────── 任务 4/5:Critic 防漂移 replan ───────────────────

def test_replan_on_drift():
    """mock Critic 返回 needs_replan -> Planner 重新 make_plan(plan_calls 增加)。"""
    adapter = _PlanExecuteAdapter(plan_steps=2, critic_needs_replan=True)
    reg = ToolRegistry()
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=adapter,
        config=AgentConfig(mode="plan_execute", max_steps=5,
                           critic_enabled=True, replan_every=1),
        state=AgentState(max_steps=5),
    )
    state = agentloop("完成某任务", ctx)
    assert state.status == "completed"
    assert adapter.plan_calls >= 2      # 原 plan + 至少一次 replan
    assert adapter.critic_calls >= 1    # Critic 被调


def test_critic_evaluates_result():
    """收尾 Critic.evaluate_result 被调;passed=False 时流程仍 complete(简化:不阻断,避免无限 replan)。"""
    adapter = _PlanExecuteAdapter(plan_steps=1, critic_passed=False)
    reg = ToolRegistry()
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=adapter,
        config=AgentConfig(mode="plan_execute", max_steps=5,
                           critic_enabled=True, replan_every=3),
        state=AgentState(max_steps=5),
    )
    state = agentloop("完成某任务", ctx)
    assert state.status == "completed"
    assert adapter.critic_calls >= 1    # 收尾 evaluate_result 被调


# ─────────────────── 任务 2':TodoWrite nudge ───────────────────

def test_todo_write_nudge():
    """关 3+ 项且无 verify 步骤 -> 返回文本含验证提示;有 verify 不触发。"""
    import agent.tools  # 触发默认工具注册(含 todo_write)
    from agent.tools import registry as default_registry
    executor = ToolExecutor(default_registry)

    todos_no_verify = [
        {"content": "做A", "status": "completed", "activeForm": "做A中"},
        {"content": "做B", "status": "completed", "activeForm": "做B中"},
        {"content": "做C", "status": "completed", "activeForm": "做C中"},
    ]
    r = executor.execute(ToolCall(call_id="n1", tool_name="todo_write",
                                  arguments={"todos": todos_no_verify}))
    assert r.ok
    assert "验证" in (r.text or "") or "验证" in json.dumps(r.data, ensure_ascii=False)

    todos_verify = [
        {"content": "做A", "status": "completed", "activeForm": "做A中"},
        {"content": "验证结果", "status": "completed", "activeForm": "验证中"},
        {"content": "做C", "status": "completed", "activeForm": "做C中"},
    ]
    r2 = executor.execute(ToolCall(call_id="n2", tool_name="todo_write",
                                   arguments={"todos": todos_verify}))
    assert r2.ok
    assert "不要直接收尾" not in (r2.text or "")


# ─────────────────── 任务 7:workflow DAG mode ───────────────────

def test_workflow_dag():
    """workflow 模式:固定 ToolCall DAG(depends_on),不调 LLM,按拓扑序执行。"""
    adapter = _PlanExecuteAdapter()
    reg = ToolRegistry()
    calls = [
        ToolCall(call_id="w1", tool_name="nope", arguments={"x": 1}),
        ToolCall(call_id="w2", tool_name="nope", arguments={"y": 2}, depends_on=["w1"]),
    ]
    state = AgentState(max_steps=5)
    state.meta["workflow_plan"] = calls
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=adapter,
        config=AgentConfig(mode="workflow", max_steps=5),
        state=state,
    )
    result = agentloop("跑工作流", ctx)
    assert result.status == "completed"
    assert len(result.tool_history) == 2   # 两个工具都执行了
    assert adapter.plan_calls == 0          # workflow 不调 LLM 决策
    assert adapter.step_calls == 0


# ─────────────────── 任务 6:推理可见性 expose_reasoning ───────────────────

def test_expose_reasoning_hides_thinking():
    """expose_reasoning=False -> ThinkingDelta 不渲染,TextDelta(最终回答)仍渲染。"""
    # False:隐藏 thinking
    buf = io.StringIO()
    p = StreamingPrinter(out=buf, use_color=False, expose_reasoning=False)
    p.emit(ThinkingDelta(text="内部推理"))
    p.emit(TextDelta(text="最终回答"))
    out = buf.getvalue()
    assert "内部推理" not in out
    assert "最终回答" in out

    # True:都渲染(thinking 用 dim)
    buf2 = io.StringIO()
    p2 = StreamingPrinter(out=buf2, use_color=False, expose_reasoning=True)
    p2.emit(ThinkingDelta(text="内部推理"))
    p2.emit(TextDelta(text="最终回答"))
    out2 = buf2.getvalue()
    assert "内部推理" in out2
    assert "最终回答" in out2
