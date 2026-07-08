from dataclasses import dataclass, field
from .enums import AgentStatus
from typing import Any, Optional
from .tools import ToolSpec, ToolCall
import time
import uuid

@dataclass
class AgentStep:
    index: int # Agent循环轮次

    model_request: Any | None = None # 模型请求的原始数据
    model_response: Any | None = None # 模型响应的原始数据

    tool_calls: list[Any] = field(default_factory=list) # Agent本轮调用的工具列表
    tool_results: list[Any] = field(default_factory=list)# Agent本轮工具执行结果列表

    error: dict[str, Any] | None = None # Agent本轮执行错误信息

    started_at: float = field(default_factory=time.perf_counter)# Agent本轮开始时间
    ended_at: float | None = None # Agent本轮结束时间
    meta: dict[str, Any] = field(default_factory=dict)# Agent本轮元数据

    def finish(self):
        """标记本轮Agent循环结束"""
        self.ended_at = time.perf_counter()
        self.meta["elapsed_ms"] = round(
            (self.ended_at - self.started_at) * 1000,
            2
        )

#终态集合:一旦进入就不再继续循环（与 AgentStatus 的终态保持一致）
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "max_steps_exceeded"}

@dataclass
class AgentState:
    """Agent运行状态，包含多轮循环的历史记录"""

    # 唯一标识符
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # 当前对话消息列表
    messages: list[Any] = field(default_factory=list)
    # 当前Agent循环的历史记录
    steps: list[AgentStep] = field(default_factory=list)
    # 当前Agent循环的轮次索引
    step_index: int = 0

    consecutive_tool_failures: int = 0 # 连续工具调用失败次数
    # 最大循环轮次，超过则停止
    max_steps: int = 5

    # AgentStatus 是 Literal 类型别名，运行时即字符串，赋值用字面量
    status: AgentStatus = "created"
    # 最终模型响应或工具执行结果
    final_response: Any | None = None
    # 当前Agent循环错误信息
    error: dict[str, Any] | None = None

    # Agent循环元数据
    meta: dict[str, Any] = field(default_factory=dict)

    def record_error(self):
        """记录一次工具调用失败，连续失败计数+1"""
        self.consecutive_tool_failures += 1

    def reset_error(self):
        """本轮工具调用成功，连续失败计数清零"""
        self.consecutive_tool_failures = 0

    def new_step(self) -> AgentStep:
        """创建一个新的Agent循环轮次"""
        step = AgentStep(index=self.step_index)
        self.steps.append(step)
        self.step_index += 1
        self.status = "running"
        return step

    def complete(self, response: Any):
        """标记Agent循环完成"""
        self.final_response = response
        self.status = "completed"

    def fail(self, error: dict[str, Any]):
        """标记Agent循环失败"""
        self.error = error
        self.status = "failed"

    def exceed_max_steps(self):
        """标记Agent循环超过最大步数（与 fail 区分，是独立终态）"""
        self.status = "max_steps_exceeded"
        self.error = {
            "type": "max_steps_exceeded",
            "message": f"Agent exceeded max steps={self.max_steps}",
            "source": "agent_runtime",
        }

    def should_continue(self) -> bool:
        """判断Agent循环是否应继续"""
        return self.status not in _TERMINAL_STATUSES and self.step_index < self.max_steps
