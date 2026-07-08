from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class ErrorInfo:
    """全局统一错误信息模型"""
    type: str                # 错误类型标识（如：ToolExecuteError、ModelRequestError）
    message: str             # 人类可读错误描述
    retryable: bool = False  # 是否支持重试
    traceback: Optional[str] = None  # 异常堆栈信息
    source: Optional[str] = None      # 错误来源（tool_executor / model_adapter / agent_runtime）
    code: Optional[str] = None       # 业务错误码
    meta: dict[str, Any] = field(default_factory=dict)  # 扩展元数据