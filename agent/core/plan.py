# Plan 数据结构(阶段 7 Planning/ReAct/Workflow)
# 纯数据层:只依赖 stdlib,不依赖 adapters/control(避免反向依赖)。
# 对齐 CC TodoItem({content, status, activeForm}) + 加 result / Plan.status。
from dataclasses import dataclass, field
from typing import Any, Literal
import time

# PlanStep 状态:pending -> in_progress -> completed
PlanStepStatus = Literal["pending", "in_progress", "completed"]
# Plan 整体状态:draft(刚生成)-> executing -> replanned(漂移重规划)/ completed
PlanStatus = Literal["draft", "executing", "replanned", "completed"]


@dataclass
class PlanStep:
    """Plan 的单个步骤。对齐 CC TodoItem,加 result(子任务结果回灌)。"""
    content: str                    # 祈使句: "Run tests"
    active_form: str                # 现在进行时: "Running tests"(UI/日志用)
    status: PlanStepStatus = "pending"
    result: str | None = None       # 子任务执行结果文本(FINISH 时的 final_response.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "active_form": self.active_form,
            "status": self.status,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanStep":
        return cls(
            content=data["content"],
            active_form=data["active_form"],
            status=data.get("status", "pending"),
            result=data.get("result"),
        )


@dataclass
class Plan:
    """一个任务的执行计划。Planner 产出,Executor 消费。"""
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = "draft"
    created_at: float = field(default_factory=time.perf_counter)

    def is_complete(self) -> bool:
        """所有 step 完成 -> Plan 完成。
        注意 all([]) == True 的坑:空 Plan 不能算完成,先判 bool(self.steps)。"""
        return bool(self.steps) and all(s.status == "completed" for s in self.steps)

    def mark_step(self, idx: int, status: PlanStepStatus, result: str | None = None):
        """标记某步状态(含可选结果)。越界索引让 Python 自然抛 IndexError。"""
        self.steps[idx].status = status
        if result is not None:
            self.steps[idx].result = result

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        return cls(
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
            status=data.get("status", "draft"),
            created_at=data.get("created_at", time.perf_counter()),
        )
