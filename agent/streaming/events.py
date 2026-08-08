# 流式事件：Agent 运行过程中向 EventSink 推送的事件类型。
#
# 三层（对应 claude-code 的双层事件模型，2026-08-08 对齐 CC 源码）：
# - 低层（adapter 发）：TextDelta / ToolCallStart / ToolCallDelta / ToolCallEnd / MessageEnd
#   —— LLM 流式输出增量（逐 token 文本、工具参数 JSON 增量）。仅 CLI 打字机消费。
# - 高层（loop / executor 发）：RunStart / StepStart / ToolStart / ToolEnd / StepEnd / RunEnd
#   —— Agent 生命周期与工具执行进度。
# - 消息级（loop 源头发）：AssistantMessage / ToolResultMessage
#   —— 完整 assistant 消息与工具结果，数据在 ModelResponse/ToolResult 处已齐，
#      直接发整包（对齐 CC QueryEngine 的 `assistant`/`user(tool_result)`，不做 delta 聚合）。
#      这是 web/SSE 消费的契约（server.py _is_web_event 白名单）；delta 只在 CLI 打字机用。
#
# 设计：frozen dataclass + StreamEvent Union；sink 用 match(event) 分发。
# 事件层不依赖 state / models / adapters，保持叶子层（与 enums 同级）。
from dataclasses import dataclass
from typing import Any, Union


# ─────────────────── 消息级：完整内容（loop 源头发，web 契约） ───────────────────

@dataclass(frozen=True)
class AssistantMessage:
    """一条完整的 assistant 消息（对齐 CC `assistant`）。

    _run_steps 拿到完整 ModelResponse（text/thinking/tool_calls/usage 全量）时源头发，
    不做 delta 聚合。tool_calls 是已解析 dict 列表 {call_id, tool_name, arguments}。
    uuid 全程带（前端去重/关联，对齐 CC）；agent_id 打标子 agent（多 Agent 展示用）。
    """
    run_id: str
    uuid: str
    agent_id: str | None = None
    step_index: int | None = None
    text: str = ""
    thinking: str = ""
    tool_calls: tuple = ()      # tuple[dict]: {call_id, tool_name, arguments}
    stop_reason: str | None = None
    usage: Any = None           # TokenUsage；用 Any 避免事件层反向依赖 models


@dataclass(frozen=True)
class ToolResultMessage:
    """一条完整工具结果（对齐 CC `user` 的 tool_result 块）。

    工具结果就绪处（_run_steps/_run_workflow/_execute_pending 的 async-for）源头发。
    elapsed_ms 由 ToolResult.elapsed_ms 传入（_parallel.run_one 实测，修待办 C 恒 0）。
    """
    run_id: str
    uuid: str
    call_id: str
    tool_name: str
    ok: bool
    summary: str | None = None
    elapsed_ms: float = 0.0
    attempts: int = 1
    error_type: str | None = None
    agent_id: str | None = None


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
    """一次 agent 运行结束（终态）。usage/duration_ms/num_steps = 本轮聚合统计
    （对齐 CC `result` 事件：整轮所有 assistant 消息 usage 累加，turn 结束才报总账；
    与每条 assistant 消息自带的 per-step usage 互补）。"""
    status: str
    final_text: str | None = None
    error: dict[str, Any] | None = None
    usage: dict[str, int] | None = None      # 本轮聚合:input/output/total/cached(不含子 agent,子 agent 各自累计)
    duration_ms: float | None = None         # 本轮耗时(首 step start ~ 末 step end)
    num_steps: int | None = None             # 本轮 step 数(对齐 CC result.num_turns)


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


@dataclass(frozen=True)
class ApprovalRequestEvent:
    """HITL:需人工批准的工具请求(web_confirmer 经 SSE 队列推前端弹窗)。

    不进 EventSink(web_confirmer 直接 put 到 SSE 队列,不走 sink/ tracer 链)。
    前端收到 -> 弹窗 -> POST /approve/{request_id} 解 future(见 guardrails/confirmer.py)。
    """
    request_id: str
    tool_name: str
    reason: str
    arguments: dict[str, Any]


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
    # 消息级（web 契约）
    AssistantMessage, ToolResultMessage,
    # 高层
    RunStart, StepStart, StepEnd, RunEnd, ToolStart, ToolEnd, ApprovalRequestEvent,
    # 低层
    TextDelta, ThinkingDelta, ToolCallStart, ToolCallDelta, ToolCallEnd, MessageEnd,
]
