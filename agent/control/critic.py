# Critic(阶段 7 Plan-and-Execute 的评审器)
# 对齐 stage7-plan §3.3/§4。调 LLM 评估结果/计划是否达标,返回 Critique。
# 对比 CC:CC 无独立 Critic(靠 TodoWrite nudge 逼模型 spawn verification subagent);我们做显式函数为学范式。
import json
import re
from dataclasses import dataclass

from ..core.messages import Message
from ..core.models import ModelRequest
from ..core.plan import Plan
from ..prompts import CRITIC_PROMPT


@dataclass
class Critique:
    passed: bool
    reason: str
    needs_replan: bool = False


class Critic:
    """调 LLM 评估结果是否达标(evaluate_result)或计划是否漂移(evaluate_plan)。"""

    def __init__(self, model_adapter):
        self.adapter = model_adapter

    async def evaluate_result(self, task: str, result: str, criteria: str | None = None) -> Critique:
        user_content = (
            f"任务:{task}\n结果:{result or '(无)'}\n"
            f"完成标准:{criteria or '任务完成且结果正确'}"
        )
        resp = await self.adapter.call_llm(ModelRequest(messages=[
            Message(role="system", content=CRITIC_PROMPT),
            Message(role="user", content=user_content),
        ]))
        return _parse_critique(resp.text or "")

    async def evaluate_plan(self, plan: Plan, state) -> Critique:
        completed = sum(1 for s in plan.steps if s.status == "completed")
        user_content = (
            f"计划:{json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)}\n"
            f"进度:已完成 {completed}/{len(plan.steps)} 步\n"
            f"评估:剩余步骤是否仍合理?是否需要重新规划(needs_replan)?"
        )
        resp = await self.adapter.call_llm(ModelRequest(messages=[
            Message(role="system", content=CRITIC_PROMPT),
            Message(role="user", content=user_content),
        ]))
        return _parse_critique(resp.text or "")


def _parse_critique(text: str) -> Critique:
    """解析 LLM 返回的 JSON -> Critique。容错:解析失败默认通过(不阻断流程)。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    raw = m.group(0) if m else text
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return Critique(passed=True, reason="评审 JSON 解析失败,默认通过", needs_replan=False)
    return Critique(
        passed=bool(data.get("passed", True)),
        reason=str(data.get("reason", "")),
        needs_replan=bool(data.get("needs_replan", False)),
    )
