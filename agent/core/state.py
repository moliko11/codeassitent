from dataclasses import dataclass, field, is_dataclass
import typing
from .errors import IllegalTransitionError
from .enums import AgentStatus
from typing import Any, Optional
import time
import uuid

 
def _ser(obj: Any) -> Any:
    """递归序列化为可 JSON 化的纯结构：dataclass -> dict(跳过 raw)，
    list/dict 递归，其他原样。产出可直接 json.dumps。

    跳过 raw：ModelResponse.raw 等是 httpx Response 等不可序列化对象，
    且 checkpoint 不需要持久化厂商原始响应。
    用 vars() 逐字段递归（不用 asdict），确保嵌套 dataclass 的 raw 也被跳过。
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _ser(v) for k, v in vars(obj).items() if k != "raw"}
    if isinstance(obj, list):
        return [_ser(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    return obj


@dataclass
class ToolHistoryEntry:
    """工具调用历史记录条目"""
    call_id: str
    tool_name: str 
    ok: bool ## 工具调用是否成功
    elapsed_ms: Optional[float] = None # 工具调用耗时（毫秒）
    error_type: Optional[str] = None   # 失败时存 type,不存 message 全文


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
    
    deadline: float | None = None # Agent本轮执行截止时间（可选）
    #\
    def to_dict(self) -> dict[str, Any]:
        """将 AgentStep 转换为字典"""
        return {
            "index": self.index,
            "model_request": _ser(self.model_request),
            "model_response": _ser(self.model_response),
            "tool_calls": _ser(self.tool_calls),
            "tool_results": _ser(self.tool_results),
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "meta": self.meta,
            "deadline": self.deadline,
        }
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentStep":
        """从字典恢复 AgentStep"""
        return cls(
            index=data["index"],
            model_request=data.get("model_request"),
            model_response=data.get("model_response"),
            tool_calls=data.get("tool_calls", []),
            tool_results=data.get("tool_results", []),
            error=data.get("error"),
            started_at=data.get("started_at", time.perf_counter()),
            ended_at=data.get("ended_at"),
            meta=data.get("meta", {}),
            deadline=data.get("deadline"),
        )
    def finish(self):
        """标记本轮Agent循环结束"""
        self.ended_at = time.perf_counter()
        self.meta["elapsed_ms"] = round(
            (self.ended_at - self.started_at) * 1000,
            2
        )

#终态集合:一旦进入就不再继续循环（与 AgentStatus 的终态保持一致）
# _TERMINAL_STATUSES = {"completed", "failed", "cancelled", "max_steps_exceeded"}

_ALLOWED_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    "created": {"running"},
    "running": {"waiting_tool", "waiting_approval", "completed",
                "failed", "max_steps_exceeded", "cancelled"},
    "waiting_tool":     {"running", "failed", "cancelled"},
    "waiting_approval": {"running", "cancelled", "failed"},
    "completed": set(), 
    "cancelled": set(), 
    "failed": set(),
    "max_steps_exceeded": set(),

}
# 终态 = 无后继的状态,从转换表派生,不再手写 set
_TERMINAL_STATUSES = {s for s, nxt in _ALLOWED_TRANSITIONS.items() if not nxt}

# 模块加载时绑定不变式:转换表的 key 必须等于 AgentStatus 的全集
assert set(typing.get_args(AgentStatus)) == set(_ALLOWED_TRANSITIONS), \
    "AgentStatus 与 _ALLOWED_TRANSITIONS 的状态集合不一致"


@dataclass
class AgentState:
    """Agent运行状态，包含多轮循环的历史记录"""

    # 唯一标识符
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # taskid: str = "" # 可选，关联到上层任务的唯一标识符
    task_id: Optional[str] = None # 可选，关联到上层任务的唯一标识符

    user_id: Optional[str] = None # 可选，关联到上层用户的唯一标识符

    session_id: Optional[str] = None # 可选，关联到上层会话的唯一标识符

    created_at: float = field(default_factory=time.perf_counter) # Agent循环开始时间
    
    updated_at: float = field(default_factory=time.perf_counter) # Agent循环状态更新时间

    timeout_at: float | None = None # Agent循环超时截止时间（可选）
    # 给模型的上下文(可被裁剪/压缩/摘要,不保证完整,生命周期跟着 context window 走
    messages: list[Any] = field(default_factory=list)
    # 执行轨迹(审计/重放/调试用,保证完整,只增不删)
    steps: list[AgentStep] = field(default_factory=list)
    # 当前Agent循环的轮次索引
    step_index: int = 0

    consecutive_tool_failures: int = 0 # 连续工具调用失败次数
    # 最大循环轮次，超过则停止
    max_steps: int = 5

    current_step: AgentStep | None = None # 当前Agent循环轮次（可选）
    
    pending_tool_calls: list[Any] = field(default_factory=list) # 当前轮次未完成的工具调用（可选）

    tool_history: list[Any] = field(default_factory=list) # 扁平化的所有tool_call记录
    # AgentStatus 是 Literal 类型别名，运行时即字符串，赋值用字面量
    status: AgentStatus = "created"

    memory: dict[str, Any] = field(default_factory=dict)        # 占位,阶段 6 Memory 系统填充
    context_summary: Optional[str] = None                        # 占位,阶段 6 压缩历史用

    # 最终模型响应或工具执行结果
    final_response: Any | None = None
    # 当前Agent循环错误信息
    error: dict[str, Any] | None = None

    version: int = 0  # 乐观锁版本号，每次状态变更 +1
    # Agent循环元数据
    meta: dict[str, Any] = field(default_factory=dict)

    def transition(self,to: AgentStatus):
        """状态转换"""
        # 1.获取当前状态的允许后继状态集合
        allowed = _ALLOWED_TRANSITIONS.get(self.status, set())
        if to not in allowed:
            raise IllegalTransitionError(self.status, to)
        self.status = to
        self.updated_at = time.perf_counter()   # 顺手解决 updated_at 不更新的老问题
        self.version += 1 # 乐观锁版本号+1
        return self
    def try_apply(self,fn, expected_version: int) -> bool:
        """
        乐观锁：仅当 version 未变时应用 fn。
        
        Args:
            fn: 修改状态的函数，接受 self 作为参数
            expected_version: 调用方期望的版本号（读取状态时获取）
        
        Returns:
            bool: True 表示修改成功，False 表示版本冲突（需重试）
        
        Example:
            state = load_state(session_id)
            expected = state.version
            
            def modify(s):
                s.transition("running")
            
            if state.try_apply(modify, expected):
                # 修改成功
                save_state(state)
            else:
                # 冲突：重新读取并重试
                state = load_state(session_id)
                # ...
        
        Note:
            当前单线程下恒成功，此方法是为阶段 10 多 Agent 共享状态铺路。
        """
        if self.version != expected_version:
            return False
        fn(self)
        return True

    def record_error(self):
        """记录一次工具调用失败，连续失败计数+1"""
        self.consecutive_tool_failures += 1

    def reset_error(self):
        """本轮工具调用成功，连续失败计数清零"""
        self.consecutive_tool_failures = 0

    def new_step(self) -> AgentStep:
        """创建一个新的Agent循环轮次"""
        # index 用 len(steps) 而非 step_index：resume 续跑会重置 step_index=0（max_steps 是单轮上限，
        # 不能让历史轮次吃掉续跑预算），重置后若仍用 step_index 会与历史 step 的 index 重复；
        # 用 len(steps) 则 live/重放/续跑都连续无冲突（live 时 len(steps)==step_index，等价）。
        step = AgentStep(index=len(self.steps))
        self.steps.append(step)
        self.step_index += 1
        # running 是循环稳态：首轮 created->running、异常恢复后 waiting_tool->running 才需转换；
        # 多轮中第二轮起 status 已是 running，重复转换会被状态机判为非法，故仅在非 running 时转换。
        if self.status != "running":
            self.transition("running")
        return step

    def complete(self, response: Any):
        """标记Agent循环完成"""
        self.final_response = response
        self.transition("completed")

    def fail(self, error: dict[str, Any]):
        """标记Agent循环失败"""
        self.error = error
        self.transition("failed")

    def exceed_max_steps(self):
        """标记Agent循环超过最大步数（与 fail 区分，是独立终态）"""
        self.transition("max_steps_exceeded")
        self.error = {
            "type": "max_steps_exceeded",
            "message": f"Agent exceeded max steps={self.max_steps}",
            "source": "agent_runtime",
        }

    def should_continue(self) -> bool:
        """判断Agent循环是否应继续"""
        return self.status not in _TERMINAL_STATUSES and self.step_index < self.max_steps

    def is_terminal(self) -> bool:
        """判断Agent循环是否已进入终态"""
        return self.status in _TERMINAL_STATUSES
    
    def to_dict(self) -> dict[str, Any]:
        """将 AgentState 转换为字典"""
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "timeout_at": self.timeout_at,
            "messages": _ser(self.messages),
            "steps": [step.to_dict() for step in self.steps],
            "step_index": self.step_index,
            "consecutive_tool_failures": self.consecutive_tool_failures,
            "max_steps": self.max_steps,
            "current_step": self.current_step.to_dict() if self.current_step else None,
            "pending_tool_calls": _ser(self.pending_tool_calls),
            "tool_history": _ser(self.tool_history),
            "status": self.status,
            "memory": self.memory,
            "context_summary": self.context_summary,
            "final_response": _ser(self.final_response),
            "error": self.error,
            "meta": self.meta,
            "version": self.version,
        }
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        """从字典恢复 AgentState"""
        state = cls(
            run_id=data["run_id"],
            task_id=data.get("task_id"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            created_at=data.get("created_at", time.perf_counter()),
            updated_at=data.get("updated_at", time.perf_counter()),
            timeout_at=data.get("timeout_at"),
            messages=data.get("messages", []),
            steps=[AgentStep.from_dict(s) for s in data.get("steps", [])],
            step_index=data.get("step_index", 0),
            consecutive_tool_failures=data.get("consecutive_tool_failures", 0),
            max_steps=data.get("max_steps", 5),
            current_step=AgentStep.from_dict(data["current_step"]) if data.get("current_step") else None,
            pending_tool_calls=data.get("pending_tool_calls", []),
            tool_history=data.get("tool_history", []),
            status=data.get("status", "created"),
            memory=data.get("memory", {}),
            context_summary=data.get("context_summary"),
            final_response=data.get("final_response"),
            error=data.get("error"),
            meta=data.get("meta", {}),
            version=data.get("version"),
        )
        return state