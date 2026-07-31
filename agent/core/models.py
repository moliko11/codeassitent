from dataclasses import dataclass, field
from .messages import Message

from typing import Any, Optional
from ..tools.defs import ToolSpec, ToolCall


@dataclass
class TokenUsage:
    """统一Token用量统计，适配所有模型厂商"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0  # Claude/OpenAI缓存token专属统计


@dataclass
class ModelRequest:
    """发给大模型的统一请求体"""
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    model: Optional[str] = None          # 模型标识
    temperature: Optional[float] = None  # 温度系数
    max_tokens: Optional[int] = None     # 最大生成长度
    thinking_budget: Optional[int] = None # 阶段 7:thinking token 预算(透传 provider,不支持则忽略)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """大模型返回的统一响应体（所有厂商归一化）"""
    response_id: Optional[str] = None
    text: Optional[str] = None                     # 纯文本回答
    tool_calls: list[ToolCall] = field(default_factory=list)  # 工具调用列表
    usage: Optional[TokenUsage] = None            # Token消耗
    stop_reason: Optional[str] = None             # 停止原因
    raw: Optional[Any] = None                     # 厂商原始响应
    meta: dict[str, Any] = field(default_factory=dict)
