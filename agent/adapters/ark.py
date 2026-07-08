# Ark 适配器（火山方舟 / 豆包，Responses API 协议）
import json
from typing import Any

from openai import OpenAI

from ..core.messages import Message
from ..core.models import ModelRequest, ModelResponse, TokenUsage
from ..tools.defs import ToolCall, ToolResult, ToolSpec
from .base import BaseModelAdapter


class ArkAdapter(BaseModelAdapter):
    """适配火山方舟 Ark /responses 端点（豆包系列模型）。

    Ark 兼容 OpenAI Responses API，与 Chat Completions 差异较大：
    - 上下文字段是 input（不是 messages），content 是 blocks 数组，原生支持多模态
    - 工具定义为扁平格式 {type:function, name, description, parameters}
    - 工具调用在 response.output 中，type=="function_call"
    - 工具结果回填为 input 中的 function_call_output 项（不是 role:tool 消息）

    注：工具调用字段名基于 OpenAI Responses API 标准推断，需用 Ark 官方文档验证。
    """

    provider = "ark"

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, base_url, model)
        # base_url 形如 https://ark.cn-beijing.volces.com/api/v3
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def call_llm(self, request: ModelRequest) -> ModelResponse:
        input_items = self._to_input(request.messages)
        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "input": input_items,
        }
        tools = self._build_tools(request.tools)
        if tools:
            kwargs["tools"] = tools
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            # Responses API 用 max_output_tokens（不是 Chat Completions 的 max_tokens）
            kwargs["max_output_tokens"] = request.max_tokens

        response = self.client.responses.create(**kwargs)
        return self._from_response(response)

    def _to_input(self, messages: list[Message]) -> list[dict[str, Any]]:
        """内部 messages -> Ark input 数组。

        约定（与 openai_compat 一致）：
        - msg.content 是 dict 且含 "type"：原样透传（function_call / function_call_output 等）
        - msg.content 是 list：扩展
        - 否则：构造 {role, content:[{type:input_text/output_text, text}]}
        """
        items: list[dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg.content, dict) and "type" in msg.content:
                items.append(msg.content)
                continue
            if isinstance(msg.content, list):
                items.extend(msg.content)
                continue
            # 文本内容：按 role 决定 content 形式
            text = str(msg.content) if msg.content is not None else ""
            if msg.role in ("system", "developer"):
                # system/developer 用字符串 content；output_text 是 assistant 输出类型，不能用于输入消息
                items.append({"role": msg.role, "content": text})
            elif msg.role == "user":
                items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
            else:  # assistant
                items.append({"role": "assistant", "content": [{"type": "output_text", "text": text}]})
        return items

    def _build_tools(self, tool_specs: list[ToolSpec]) -> list[dict[str, Any]]:
        # Responses API 扁平格式（无 function 嵌套层）
        out = []
        for ts in tool_specs:
            desc = ts.description
            if ts.returns:
                desc += f"\n返回: {ts.returns}"
            if ts.examples:
                desc += f"\n示例: {json.dumps(ts.examples, ensure_ascii=False)}"
            out.append({
                "type": "function",
                "name": ts.name,
                "description": desc,
                "parameters": ts.input_schema,
            })
        return out

    def _from_response(self, response: Any) -> ModelResponse:
        """解析 Responses API 响应 -> ModelResponse"""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for item in getattr(response, "output", None) or []:
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for block in getattr(item, "content", None) or []:
                    if getattr(block, "type", None) in ("output_text", "text"):
                        text_parts.append(getattr(block, "text", "") or "")
            elif item_type == "function_call":
                args_str = getattr(item, "arguments", "{}") or "{}"
                try:
                    parsed_args = json.loads(args_str)
                except json.JSONDecodeError:
                    parsed_args = {"_raw_arguments": args_str}
                tool_calls.append(
                    ToolCall(
                        call_id=getattr(item, "call_id", None) or getattr(item, "id", ""),
                        tool_name=getattr(item, "name", ""),
                        arguments=parsed_args,
                        raw=item.model_dump() if hasattr(item, "model_dump") else item,
                        meta={"provider": "ark"},
                    )
                )

        usage = None
        if getattr(response, "usage", None) is not None:
            u = response.usage
            usage = TokenUsage(
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                total_tokens=getattr(u, "total_tokens", 0) or 0,
            )

        return ModelResponse(
            response_id=getattr(response, "id", None),
            text="".join(text_parts) or None,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=getattr(response, "status", None),
            raw=response.model_dump() if hasattr(response, "model_dump") else response,
            meta={"provider": "ark"},
        )

    def append_tool_results(
        self,
        messages: list[Message],
        model_response: ModelResponse,
        tool_results: list[ToolResult],
    ) -> list[Message]:
        """回填 assistant 的 function_call + 各工具结果。

        Responses API：function_call 与 function_call_output 都是 input 数组里的项，
        不需要 role:tool 消息。这里用 Message 包装，content 存 dict，_to_input 原样透传。
        """
        new_messages = list(messages)

        # 1) 追加每个 function_call 项（assistant 发起的工具调用）
        if model_response.tool_calls:
            for tc in model_response.tool_calls:
                args = tc.arguments
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)
                new_messages.append(
                    Message(
                        role="assistant",
                        content={
                            "type": "function_call",
                            "call_id": tc.call_id,
                            "name": tc.tool_name,
                            "arguments": args or "{}",
                        },
                    )
                )

        # 2) 追加每个工具结果（function_call_output）
        for result in tool_results:
            new_messages.append(
                Message(
                    role="user",
                    content={
                        "type": "function_call_output",
                        "call_id": result.call_id,
                        "output": self._tool_result_to_text(result),
                    },
                )
            )

        return new_messages
