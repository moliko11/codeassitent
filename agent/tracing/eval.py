# tracing/eval.py - Eval 框架:GoldenDataset + Evaluator + regression_eval(阶段9 任务4,题9-14)
# 复用 _ScriptedAdapter mock 跑 dataset(不依赖真实 LLM);规则打分,LLM-as-judge 留 TODO。
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GoldenCase:
    """golden dataset 单条:input + 期望(工具/答案/标准)。"""
    input: str
    expected_tools: Optional[list[str]] = None
    expected_answer: Optional[str] = None
    eval_criteria: Optional[str] = None


@dataclass
class CaseResult:
    """单条 case 的评估结果。"""
    case: GoldenCase
    actual_tools: list[str] = field(default_factory=list)
    actual_answer: str = ""
    tool_accuracy: float = 0.0      # 期望工具命中比例(0-1)
    answer_grounded: bool = False   # 答案是否 grounded(规则:子串匹配)
    status: str = "unknown"

    @property
    def score(self) -> float:
        """综合分:tool_accuracy * 0.5 + answer_grounded * 0.5。"""
        return self.tool_accuracy * 0.5 + (1.0 if self.answer_grounded else 0.0) * 0.5


class Evaluator:
    """跑 golden dataset,对每条打分。复用 agentloop + mock adapter(不依赖真实 LLM)。"""

    def __init__(self, registry):
        self.registry = registry

    def run(self, dataset: list[GoldenCase], adapter, config=None) -> list[CaseResult]:
        from ..agentloop import agentloop
        from ..runtime import RuntimeContext
        from ..config.config import AgentConfig
        from ..core.state import AgentState
        from ..tools.registry import ToolExecutor
        from ..streaming.sink import NullSink

        cfg = config or AgentConfig(max_steps=5)
        results = []
        for case in dataset:
            state = AgentState(max_steps=cfg.max_steps)
            ctx = RuntimeContext(
                registry=self.registry, tool_executor=ToolExecutor(self.registry),
                model_adapter=adapter, config=cfg, state=state, sink=NullSink(),
            )
            try:
                agentloop(case.input, ctx)
            except Exception:
                pass  # 评估不因单条崩而中断
            actual_tools = [h.tool_name for h in state.tool_history]
            actual_answer = getattr(state.final_response, "text", "") if state.final_response else ""
            results.append(CaseResult(
                case=case,
                actual_tools=actual_tools,
                actual_answer=actual_answer,
                tool_accuracy=self._tool_accuracy(case.expected_tools, actual_tools),
                answer_grounded=self._answer_grounded(case.expected_answer, actual_answer),
                status=state.status,
            ))
        return results

    def regression_eval(self, dataset, before_adapter, after_adapter, config=None) -> dict:
        """改 prompt/模型 前后跑同 dataset,对比分数是否退化。"""
        before = self.run(dataset, before_adapter, config)
        after = self.run(dataset, after_adapter, config)
        n = max(len(before), len(after)) or 1
        before_score = sum(r.score for r in before) / n
        after_score = sum(r.score for r in after) / n
        return {
            "before_score": round(before_score, 3),
            "after_score": round(after_score, 3),
            "delta": round(after_score - before_score, 3),
            "regressed": after_score < before_score,
            "before_results": before,
            "after_results": after,
        }

    @staticmethod
    def _tool_accuracy(expected: Optional[list[str]], actual: list[str]) -> float:
        if not expected:
            return 1.0  # 无期望工具 = 不评估此项,满分
        matched = sum(1 for t in expected if t in actual)
        return matched / len(expected)

    @staticmethod
    def _answer_grounded(expected: Optional[str], actual: str) -> bool:
        if not expected:
            return True  # 无期望答案 = 不评估
        # 简化:子串匹配(双向)。LLM-as-judge 留 TODO。
        e, a = expected.lower(), actual.lower()
        return e in a or a in e
