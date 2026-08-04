# OpenAI 兼容适配器（Chat Completions 协议）：DeepSeek / OpenAI 等
import json
from typing import Any

from openai import AsyncOpenAI

from ..core.messages import Message
from ..core.models import ModelRequest, ModelResponse, TokenUsage
from ..tools.defs import ToolCall, ToolResult, ToolSpec
from ..streaming.sink import EventSink
from ..streaming.events import TextDelta, ThinkingDelta, ToolCallStart, ToolCallDelta, ToolCallEnd, MessageEnd
from .base import BaseModelAdapter


class OpenAICompatibleAdapter(BaseModelAdapter):
    """适配 OpenAI Chat Completions 协议的供应商（DeepSeek/OpenAI 等）。

    DeepSeek 兼容 /v1/chat/completions，但不支持 /v1/responses，
    所以用 client.chat.completions.create 而非 client.responses.create。
    """

    provider = "openai_compatible"

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, base_url, model)
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def call_llm(self, request: ModelRequest) -> ModelResponse:
        messages = self._to_chat_messages(request.messages)
        tools = self._to_chat_tools(request.tools)

        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            # Chat Completions 用 max_tokens（不是 Responses API 的 max_output_tokens）
            kwargs["max_tokens"] = request.max_tokens
        if "tool_choice" in request.meta:
            kwargs["tool_choice"] = request.meta["tool_choice"]
        if "parallel_tool_calls" in request.meta:
            kwargs["parallel_tool_calls"] = request.meta["parallel_tool_calls"]
        # TODO(阶段7): request.thinking_budget 透传 provider(DeepSeek enable_thinking/reasoning_budget?参数名待真实联调确认,暂不传避免 provider 拒绝)

        response = await self.client.chat.completions.create(**kwargs)
        return self._from_chat_response(response)

    async def stream_llm(self, request: ModelRequest, sink: EventSink) -> ModelResponse:
        """Chat Completions 真流式：stream=True 逐 chunk 迭代，边收边推事件。

        - delta.content -> TextDelta（逐 token 文本）
        - delta.tool_calls[i]：首次见 index i 发 ToolCallStart（拿 id/name）；
          后续 function.arguments 发 ToolCallDelta，累积进 args 缓冲
        - 收尾：每个 tool_call 发 ToolCallEnd + json.loads 解析参数；发 MessageEnd(usage)
        - 返回累积好的 ModelResponse（字段与 _from_chat_response 一致）

        异常（超时/认证/限流）原样抛出，交由 agentloop 的 classify_error 处理。
        """
        messages = self._to_chat_messages(request.messages)
        tools = self._to_chat_tools(request.tools)

        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if "tool_choice" in request.meta:
            kwargs["tool_choice"] = request.meta["tool_choice"]
        if "parallel_tool_calls" in request.meta:
            kwargs["parallel_tool_calls"] = request.meta["parallel_tool_calls"]

        stream = await self.client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}  # index -> {call_id, name, args}
        usage: TokenUsage | None = None
        stop_reason: str | None = None
        response_id: str | None = None

        async for chunk in stream:
            if getattr(chunk, "id", None):
                response_id = chunk.id
            # usage-only chunk（choices 为空）通常在流末尾
            if getattr(chunk, "usage", None) is not None:
                u = chunk.usage
                usage = TokenUsage(
                    input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(u, "completion_tokens", 0) or 0,
                    total_tokens=getattr(u, "total_tokens", 0) or 0,
                    cached_tokens=self._extract_cached_tokens(u),
                )
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.delta

            # 文本增量
            content = getattr(delta, "content", None)
            if content:
                text_parts.append(content)
                sink.emit(TextDelta(text=content))

            # thinking/reasoning 增量(阶段7):DeepSeek 的 reasoning_content,推 ThinkingDelta
            # 与 text 分开:reasoning 是内部 CoT(暴露受 expose_reasoning 控制),text 是最终回答始终显示
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                sink.emit(ThinkingDelta(text=reasoning))

            # 工具调用增量
            for tc_delta in getattr(delta, "tool_calls", None) or []:
                idx = tc_delta.index if tc_delta.index is not None else 0
                acc = tool_acc.get(idx)
                if acc is None:
                    # 首次：id / name 只在首帧出现
                    call_id = getattr(tc_delta, "id", None) or ""
                    fn = getattr(tc_delta, "function", None)
                    name = (getattr(fn, "name", None) or "") if fn else ""
                    acc = {"call_id": call_id, "name": name, "args": ""}
                    tool_acc[idx] = acc
                    sink.emit(ToolCallStart(call_id=call_id, tool_name=name, index=idx))
                fn = getattr(tc_delta, "function", None)
                arg_chunk = getattr(fn, "arguments", None) if fn else None
                if arg_chunk:
                    acc["args"] += arg_chunk
                    sink.emit(ToolCallDelta(call_id=acc["call_id"], arguments_delta=arg_chunk))

            if getattr(choice, "finish_reason", None):
                stop_reason = choice.finish_reason

        # 收尾：解析每个 tool_call 的完整参数
        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_acc):
            acc = tool_acc[idx]
            sink.emit(ToolCallEnd(call_id=acc["call_id"]))
            try:
                parsed_args = json.loads(acc["args"]) if acc["args"] else {}
            except json.JSONDecodeError:
                parsed_args = {"_raw_arguments": acc["args"]}
            tool_calls.append(ToolCall(
                call_id=acc["call_id"],
                tool_name=acc["name"],
                arguments=parsed_args,
                meta={"provider": "openai_compatible", "tool_call_id": acc["call_id"]},
            ))

        sink.emit(MessageEnd(stop_reason=stop_reason, usage=usage))

        return ModelResponse(
            response_id=response_id,
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=stop_reason,
            raw=None,
            meta={"provider": "openai_compatible", "streamed": True},
        )

    def _to_chat_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """把内部 Message 转成 Chat Completions 的 messages 数组。

        约定：若 msg.content 本身就是一条完整的 chat message dict（含 "role"），
        就原样透传——用于携带 tool_calls 的 assistant 消息和 tool 结果消息。
        """
        items: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg.content, dict) and "role" in msg.content:
                items.append(msg.content)
                continue
            if isinstance(msg.content, list):
                items.extend(msg.content)
                continue
            items.append(
                {
                    "role": msg.role,
                    "content": str(msg.content) if msg.content is not None else "",
                }
            )
        return items
    def _to_chat_tools(self, tool_specs):
        out = []
        for ts in tool_specs:
            desc = ts.description
            if ts.returns:
                desc += f"\n返回: {ts.returns}"
            if ts.examples:
                desc += f"\n示例: {json.dumps(ts.examples, ensure_ascii=False)}"
            out.append({"type": "function", "function": {
                "name": ts.name, "description": desc, "parameters": ts.input_schema}})
        return out

    def _from_chat_response(self, response: Any) -> ModelResponse:
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            fn = tc.function
            arguments = getattr(fn, "arguments", "{}") or "{}"
            try:
                parsed_args = json.loads(arguments)
            except json.JSONDecodeError:
                parsed_args = {"_raw_arguments": arguments}
            tool_calls.append(
                ToolCall(
                    call_id=tc.id,
                    tool_name=fn.name,
                    arguments=parsed_args,
                    raw=tc.model_dump() if hasattr(tc, "model_dump") else tc,
                    meta={"provider": "openai_compatible", "tool_call_id": tc.id},
                )
            )

        usage = None
        if getattr(response, "usage", None) is not None:
            usage = TokenUsage(
                input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
                cached_tokens=self._extract_cached_tokens(response.usage),
            )

        return ModelResponse(
            response_id=getattr(response, "id", None),
            text=getattr(msg, "content", None),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=getattr(choice, "finish_reason", None),
            raw=response.model_dump() if hasattr(response, "model_dump") else response,
            meta={"provider": "openai_compatible"},
        )

    def append_assistant(
        self, messages: list[Message], model_response: ModelResponse
    ) -> list[Message]:
        """追加 assistant 消息（Chat Completions 格式）。
        有 tool_calls -> 带 tool_calls 的 assistant；无 tool_calls -> 纯 text assistant
        （最终回答也进 messages 作历史，推翻 Decision 3：多轮需要上一轮 final 作上下文）。"""
        new_messages = list(messages)
        if model_response.tool_calls:
            tool_calls = []
            for tc in model_response.tool_calls:
                args = tc.arguments
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                tool_calls.append({
                    "id": tc.call_id,
                    "type": "function",
                    "function": {"name": tc.tool_name, "arguments": args or "{}"},
                })
            new_messages.append(Message(
                role="assistant",
                content={
                    "role": "assistant",
                    "content": model_response.text or None,
                    "tool_calls": tool_calls,
                },
            ))
        else:
            # 最终回答：纯 text assistant（_to_chat_messages else 分支转 {role:assistant, content:text}）
            new_messages.append(Message(
                role="assistant",
                content=model_response.text or "",
            ))
        return new_messages

    def append_tool_result(
        self, messages: list[Message], result: ToolResult
    ) -> list[Message]:
        """追加单条 tool 结果（role=tool，带 tool_call_id）。"""
        new_messages = list(messages)
        new_messages.append(Message(
            role="tool",
            content={
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": self._tool_result_to_text(result),
            },
        ))
        return new_messages