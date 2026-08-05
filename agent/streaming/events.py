# 流式事件：Agent 运行过程中向 EventSink 推送的事件类型。
#
# 分两层（对应 claude-code 的双层事件模型）：
# - 低层（adapter 发）：TextDelta / ToolCallStart / ToolCallDelta / ToolCallEnd / MessageEnd
#   —— 对应 LLM 流式输出的增量（逐 token 文本、工具参数 JSON 增量）。
# - 高层（loop / executor 发）：RunStart / StepStart / ToolStart / ToolEnd / StepEnd / RunEnd
#   —— 对应 Agent 生命周期与工具执行进度。
#
# 设计：frozen dataclass + StreamEvent Union；sink 用 match(event) 分发。
# 事件层不依赖 state / models / adapters，保持叶子层（与 enums 同级）。
from dataclasses import dataclass
from typing import Any, Union


# ─────────────────── 高层：生命周期（loop / executor 发） ───────────────────

@dataclass(frozen=True)
class RunStart:
    """一次 agent 运行开始"""
    run_id: str


@dataclass(frozen=True)
class StepStart:
    """一轮 Agent 循环开始"""
    step_index: int


@dataclass(frozen=True)
class StepEnd:
    """一轮 Agent 循环结束"""
    step_index: int


@dataclass(frozen=True)
class RunEnd:
    """一次 agent 运行结束（终态）"""
    status: str
    final_text: str | None = None
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolStart:
    """即将执行某工具（executor 发）"""
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolEnd:
    """工具执行完毕（executor 发）"""
    call_id: str
    tool_name: str
    ok: bool
    elapsed_ms: float = 0.0
    error_type: str | None = None
    summary: str | None = None
    attempts: int = 1   # 实际尝试次数(含首次);>1 表示发生过重试,MetricsCollector 算 retry_count 用(#6)


# ─────────────────── 低层：LLM 流式增量（adapter 发） ───────────────────

@dataclass(frozen=True)
class TextDelta:
    """一段流式文本（可能几个字，也可能整段——非流式 fallback 时是整段）"""
    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    """一段流式 thinking/reasoning 增量（模型内部 CoT，区别于最终回答 TextDelta）。
    DeepSeek 的 reasoning_content / ark 的 thinking / Claude 的 thinking block。
    expose_reasoning=False 时 printer 不渲染（对齐 CC 隐藏内部推理），最终回答(TextDelta)始终可见。"""
    text: str


@dataclass(frozen=True)
class ToolCallStart:
    """模型开始产出第 index 个工具调用（拿到 call_id / tool_name）"""
    call_id: str
    tool_name: str
    index: int = 0


@dataclass(frozen=True)
class ToolCallDelta:
    """工具调用参数 JSON 的增量片段"""
    call_id: str
    arguments_delta: str


@dataclass(frozen=True)
class ToolCallEnd:
    """一个工具调用的参数收完（可解析为完整 arguments）"""
    call_id: str


@dataclass(frozen=True)
class MessageEnd:
    """本轮 LLM 消息结束"""
    stop_reason: str | None = None
    usage: Any = None  # TokenUsage；用 Any 避免事件层反向依赖 models


StreamEvent = Union[
    # 高层
    RunStart, StepStart, StepEnd, RunEnd, ToolStart, ToolEnd,
    # 低层
    TextDelta, ThinkingDelta, ToolCallStart, ToolCallDelta, ToolCallEnd, MessageEnd,
]
