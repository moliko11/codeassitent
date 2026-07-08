# 模型适配器抽象基类
import json
from abc import ABC, abstractmethod

from ..core.messages import Message
from ..core.models import ModelRequest, ModelResponse
from ..tools.defs import ToolResult


class BaseModelAdapter(ABC):
    """所有模型供应商适配器的统一接口。

    职责：把内部统一的 ModelRequest 翻译成 provider 特定请求，调用 provider API，
    再把响应翻译回内部统一的 ModelResponse。
    agentloop 只依赖本接口，不感知具体 provider。
    新增 provider = 实现一个子类 + 在 make_adapter 注册一行。
    """

    provider: str = ""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @abstractmethod
    def call_llm(self, request: ModelRequest) -> ModelResponse:
        """ModelRequest(统一) -> provider请求 -> 调API -> ModelResponse(统一)"""

    @abstractmethod
    def append_tool_results(
        self,
        messages: list[Message],
        model_response: ModelResponse,
        tool_results: list[ToolResult],
    ) -> list[Message]:
        """按 provider 格式把 tool 结果回填到 messages（各 provider 格式不同，必须各自实现）"""

    def _tool_result_to_text(self, result: ToolResult) -> str:
        """把 ToolResult 转成文本（通用实现，子类可覆盖）"""
        if result.text is not None:
            return result.text
        if result.ok:
            return json.dumps(
                {"ok": True, "tool_name": result.tool_name, "data": result.data},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "ok": False,
                "tool_name": result.tool_name,
                "error": {
                    "type": result.error["type"] if result.error else "UnknownError",
                    "message": result.error["message"] if result.error else "Unknown error",
                    "retryable": result.error["retryable"] if result.error else False,
                },
            },
            ensure_ascii=False,
        )
