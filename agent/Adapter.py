import json
from typing import Any
from openai import OpenAI

from agent.tools import ToolCall, ToolResult, ToolSpec
from .messages import Message
from .models import ModelRequest, ModelResponse, TokenUsage


class OpenAIAdapter:
    def __init__(self, api_key: str | None = None):
        # TODO: 这个 key 已暴露在源码里，建议去 DeepSeek 控制台重置后改用环境变量
        self.client = OpenAI(
            api_key="sk-91d255b4dc3b449d8975cb38461913d6",
            base_url="https://api.deepseek.com",
        )

    def call_llm(self, request: ModelRequest) -> ModelResponse:
        """
        把内部统一的 ModelRequest 转成 Chat Completions 请求，
        再把 OpenAI 兼容响应转成内部统一的 ModelResponse。

        DeepSeek 兼容 OpenAI 的 /v1/chat/completions，但不支持 /v1/responses，
        所以这里用 client.chat.completions.create 而不是 client.responses.create。
        """
        messages = self._to_chat_messages(request.messages)
        tools = self._to_chat_tools(request.tools)

        kwargs: dict[str, Any] = {
            "model": request.model or "deepseek-v4-pro",
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        if request.max_tokens is not None:
            # Chat Completions 用 max_tokens（不是 Responses API 的 max_output_tokens）
            kwargs["max_tokens"] = request.max_tokens

        # 可选：透传一些 OpenAI 特有参数
        if "tool_choice" in request.meta:
            kwargs["tool_choice"] = request.meta["tool_choice"]

        if "parallel_tool_calls" in request.meta:
            kwargs["parallel_tool_calls"] = request.meta["parallel_tool_calls"]

        response = self.client.chat.completions.create(**kwargs)

        return self._from_chat_response(response)

    def _to_chat_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """
        把内部 Message 转成 Chat Completions 的 messages 数组。

        约定：如果 msg.content 本身就是一条完整的 chat message dict（含 "role"），
        就原样透传——用于携带 tool_calls 的 assistant 消息和 tool 结果消息。
        """
        items: list[dict[str, Any]] = []

        for msg in messages:
            if isinstance(msg.content, dict) and "role" in msg.content:
                # 已经是 chat message dict，直接透传
                items.append(msg.content)
                continue

            if isinstance(msg.content, list):
                # 多条 chat message 一起扩展
                items.extend(msg.content)
                continue

            items.append(
                {
                    "role": msg.role,
                    "content": str(msg.content) if msg.content is not None else "",
                }
            )

        return items

    def _to_chat_tools(self, tool_specs: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": ts.name,
                    "description": ts.description,
                    "parameters": ts.input_schema,
                },
            }
            for ts in tool_specs
        ]

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
                parsed_args = {
                    "_raw_arguments": arguments
                }

            tool_calls.append(
                ToolCall(
                    call_id=tc.id,
                    tool_name=fn.name,
                    arguments=parsed_args,
                    raw=tc.model_dump() if hasattr(tc, "model_dump") else tc,
                    meta={
                        "provider": "deepseek",
                        "tool_call_id": tc.id,
                    },
                )
            )

        usage = None
        if getattr(response, "usage", None) is not None:
            usage = TokenUsage(
                input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
            )

        return ModelResponse(
            response_id=getattr(response, "id", None),
            text=getattr(msg, "content", None),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=getattr(choice, "finish_reason", None),
            raw=response.model_dump() if hasattr(response, "model_dump") else response,
            meta={
                "provider": "deepseek",
            },
        )

    def append_tool_results(
        self,
        messages: list[Message],
        model_response: ModelResponse,
        tool_results: list[ToolResult],
    ) -> list[Message]:
        """
        把上一次模型返回的 assistant tool_calls 消息 + 各工具执行结果
        一起追加到 messages，供下一次 Chat Completions 请求使用。

        Chat Completions 要求：tool 结果消息之前必须有一条发起 tool_calls
        的 assistant 消息，且每条 tool 结果要带匹配的 tool_call_id。
        """
        new_messages = list(messages)

        # 1) 追加带 tool_calls 的 assistant 消息
        if model_response.tool_calls:
            tool_calls = []
            for tc in model_response.tool_calls:
                args = tc.arguments
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                tool_calls.append(
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": args or "{}",
                        },
                    }
                )

            new_messages.append(
                Message(
                    role="assistant",
                    content={
                        "role": "assistant",
                        "content": model_response.text or None,
                        "tool_calls": tool_calls,
                    },
                )
            )

        # 2) 追加每个工具结果（role=tool，需带 tool_call_id）
        for result in tool_results:
            new_messages.append(
                Message(
                    role="tool",
                    content={
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": self._tool_result_to_text(result),
                    },
                )
            )

        return new_messages

    def _tool_result_to_text(self, result: ToolResult) -> str:
        if result.text is not None:
            return result.text

        if result.ok:
            return json.dumps(
                {
                    "ok": True,
                    "tool_name": result.tool_name,
                    "data": result.data,
                },
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
