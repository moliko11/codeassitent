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


class StepTimeout(Exception):
    """Agent 循环单轮超时异常"""
    pass

class IllegalTransitionError(Exception):
    def __init__(self, frm, to):
        self.frm, self.to = frm, to
        super().__init__(f"非法状态转换: {frm} -> {to}")

# 不可重试的 HTTP 状态码：认证/授权/参数/配置类，重试必失败
_NON_RETRYABLE_STATUS = {400, 401, 403, 404, 422}


def _status_code(e: BaseException) -> Optional[int]:
    """从异常提取 HTTP status_code（openai sdk 异常都带；连接/超时类没有）"""
    code = getattr(e, "status_code", None)
    if code is None:
        code = getattr(getattr(e, "response", None), "status_code", None)
    return code


def classify_error(e: BaseException) -> dict[str, Any]:
    """按异常类型判断 retryable，返回结构化 error dict。

    - 401/403/400/404/422 -> 不可重试（重试必失败）
    - 429/5xx/无 status（连接错/超时/StepTimeout/格式错）-> 可重试
    """
    name = type(e).__name__
    status = _status_code(e)
    if status in _NON_RETRYABLE_STATUS:
        return {"type": name, "message": str(e), "source": "model_adapter",
                "retryable": False, "status_code": status}
    return {"type": name, "message": str(e), "source": "agentloop",
            "retryable": True, "status_code": status}
