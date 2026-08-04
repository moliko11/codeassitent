# 模型适配器抽象基类
import json
from abc import ABC, abstractmethod

from ..core.messages import Message
from ..core.models import ModelRequest, ModelResponse
from ..tools.defs import ToolResult
from ..streaming.sink import EventSink
from ..streaming.events import TextDelta, ToolCallStart, ToolCallEnd, MessageEnd


class BaseModelAdapter(ABC):
    """所有模型供应商适配器的统一接口。

    职责：把内部统一的 ModelRequest 翻译成 provider 特定请求，调用 provider API，
    再把响应翻译回内部统一的 ModelResponse。
    agentloop 只依赖本接口，不感知具体 provider。
    新增 provider = 实现一个子类 + 在 make_adapter 注册一行。
    """

    provider: str = ""

    @staticmethod
    def _extract_cached_tokens(u) -> int:
        """从 provider usage 对象提取 cached_tokens(各厂字段名不同,兼容取)。
        DeepSeek: prompt_cache_hit_tokens;OpenAI Chat: prompt_tokens_details.cached_tokens;
        豆包/Responses API: input_tokens_details.cached_tokens;其他: 顶层 cached_tokens。无则返 0。
        注:cached 是 input 的子集(命中的缓存输入),命中率 = cached / input_tokens。"""
        v = getattr(u, "prompt_cache_hit_tokens", None)       # DeepSeek
        if v:
            return int(v)
        # OpenAI Chat: prompt_tokens_details;豆包/Responses: input_tokens_details(同结构,字段名不同)
        for detail_attr in ("prompt_tokens_details", "input_tokens_details"):
            pd = getattr(u, detail_attr, None)
            if pd is not None:
                v = getattr(pd, "cached_tokens", None)
                if v:
                    return int(v)
        v = getattr(u, "cached_tokens", None)                 # 顶层(部分 provider)
        if v:
            return int(v)
        return 0

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    @abstractmethod
    async def call_llm(self, request: ModelRequest) -> ModelResponse:
        """ModelRequest(统一) -> provider请求 -> 调API -> ModelResponse(统一)"""

    async def stream_llm(self, request: ModelRequest, sink: EventSink) -> ModelResponse:
        """流式调用 LLM：边收边把增量事件推给 sink，返回累积好的 ModelResponse。

        默认实现：退化为阻塞 call_llm，再把整包拆成事件一次性推给 sink。
        真实 provider 子类覆盖此方法做逐 token 流式（见 openai_compat / ark）。

        兼容性关键：不支持流式的 provider 与测试 mock 只需实现 call_llm，
        即可自动获得本方法 -> 流式对它们透明（只是「一次吐整段」而非逐 token）。
        """
        resp = await self.call_llm(request)
        if resp.text:
            sink.emit(TextDelta(text=resp.text))
        for i, tc in enumerate(resp.tool_calls):
            sink.emit(ToolCallStart(call_id=tc.call_id, tool_name=tc.tool_name, index=i))
            sink.emit(ToolCallEnd(call_id=tc.call_id))
        sink.emit(MessageEnd(stop_reason=resp.stop_reason, usage=resp.usage))
        return resp



    @abstractmethod
    def append_assistant(
        self, messages: list[Message], model_response: ModelResponse
    ) -> list[Message]:
        """按 provider 格式把 assistant 消息追加到 messages。
        解耦（硬伤 3）：assistant 单独 append，不再 deferred 到 results。
        有 tool_calls -> 带 tool_calls 的 assistant；无 tool_calls -> 纯 text assistant
        （最终回答也进 messages 作历史，多轮对话需要上一轮 final 作上下文，推翻 Decision 3）。"""
    
    @abstractmethod
    def append_tool_result(
        self, messages: list[Message], result: ToolResult
    ) -> list[Message]:
        """按 provider 格式把单条 tool 结果追加到 messages。逐 result 增量（硬伤 1，非批量）。"""


    # @abstractmethod
    # def append_tool_results(
    #     self,
    #     messages: list[Message],
    #     model_response: ModelResponse,
    #     tool_results: list[ToolResult],
    # ) -> list[Message]:
    #     """按 provider 格式把 tool 结果回填到 messages（各 provider 格式不同，必须各自实现）"""
    def append_tool_results(
        self,
        messages: list[Message],
        model_response: ModelResponse,
        tool_results: list[ToolResult],
    ) -> list[Message]:
        """兼容旧接口 = append_assistant + 逐条 append_tool_result。
        agentloop 改造后不再调本方法，保留给其他调用方/测试。"""
        new_messages = self.append_assistant(messages, model_response)
        for r in tool_results:
            new_messages = self.append_tool_result(new_messages, r)
        return new_messages

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
