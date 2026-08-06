# Planner(阶段 7 Plan-and-Execute 的规划器)
# 对齐 stage7-plan §3.3/§4。Planner 调 1 次 LLM 产 Plan;Executor 在 agentloop._run_plan_execute。
# 对比 CC:CC 无独立 Planner(纯 ReAct + TodoWrite 工具做轻量规划);我们做显式组件为学范式。
import json
import re

from ..core.messages import Message
from ..core.models import ModelRequest
from ..core.plan import Plan, PlanStep
from ..prompts import PLAN_PROMPT


class Planner:
    """调 LLM 把任务拆解为结构化 Plan(step 列表)。
    prior 非 None 时为 replan:把原 plan 给 LLM 修订。"""

    def __init__(self, model_adapter):
        self.adapter = model_adapter

    async def make_plan(self, task: str, registry=None, prior: Plan | None = None) -> Plan:
        tools_desc = ""
        if registry is not None:
            try:
                tools_desc = ", ".join(t.tool_spec.name for t in registry.list_tools())
            except Exception:
                tools_desc = ""
        user_content = f"任务:{task}"
        if tools_desc:
            user_content += f"\n可用工具:{tools_desc}"
        if prior is not None:
            user_content += (
                "\n\n原计划(需修订,已完成步骤标 completed,请据此调整剩余步骤):\n"
                + json.dumps(prior.to_dict(), ensure_ascii=False, indent=2)
            )
        resp = await self.adapter.call_llm(ModelRequest(
            messages=[
                Message(role="system", content=PLAN_PROMPT),
                Message(role="user", content=user_content),
            ],
        ))
        return _parse_plan(resp.text or "")


def _parse_plan(text: str) -> Plan:
    """解析 LLM 返回的 JSON -> Plan。容错:解析失败退化为单步 Plan(把原文当任务描述)。"""
    m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    raw = m.group(0) if m else text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Plan(steps=[PlanStep(content=text.strip() or "完成任务",
                                    active_form="完成任务")], status="draft")
    # 兼容 {"steps":[...]} 或裸 [...]
    steps_data = data.get("steps", data) if isinstance(data, dict) else data
    if not isinstance(steps_data, list):
        return Plan(steps=[PlanStep(content=str(data), active_form="完成任务")], status="draft")
    steps = []
    for s in steps_data:
        if not isinstance(s, dict):
            continue
        content = s.get("content") or s.get("desc") or s.get("description") or "完成任务"
        active_form = s.get("active_form") or s.get("activeForm") or content
        steps.append(PlanStep(content=content, active_form=active_form))
    if not steps:
        steps = [PlanStep(content="完成任务", active_form="完成任务")]
    return Plan(steps=steps, status="draft")
