# 对话消息数据模型（最底层，仅依赖 enums）
# 注意：本模块不依赖 state / Adapter / config 等上层，避免循环导入
from dataclasses import dataclass, field
from typing import Any

from .enums import Role, ContentType


@dataclass
class Message:
    """统一对话消息（精简版，通用推荐）。

    结构化约定（修 provider 格式泄漏，见 docs）：
    - content: 恒为文本（str）。assistant 的工具调用不塞 content——
      放 meta["tool_calls"]（list of {call_id, tool_name, arguments}）；
      tool 结果放 meta["tool_call_id"]（关联 call_id）。
    - meta: 溯源/时间/结构化工具载荷。适配器把内部 Message 转 provider wire 格式
      只发生在各自 _to_* 转换器（openai_compat._to_chat_message / ark._to_input），
      不再把含 role/type 的 provider dict 塞进 content。
    """
    role: Role
    content: Any  # 恒为 str（文本）；保留 Any 供多模态/旧数据防御
    meta: dict[str, Any] = field(default_factory=dict)  # 结构化工具载荷(tool_calls/tool_call_id)+ 溯源标签

    @property
    def tool_calls(self) -> list[dict]:
        """assistant 消息的结构化 tool_calls（meta 存，无则空）。"""
        return self.meta.get("tool_calls", []) if self.role == "assistant" else []

    @property
    def tool_call_id(self) -> str | None:
        """tool 消息关联的 call_id（meta 存；非 tool 消息 None）。"""
        return self.meta.get("tool_call_id") if self.role == "tool" else None

@dataclass
class ContentBlock:
    """精细化消息内容块，支持多模态拆分"""
    type: ContentType
    data: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class RichMessage:
    """精细化对话消息（生产级，适配多模态、工具、推理）"""
    role: Role
    content: list[ContentBlock]
    meta: dict[str, Any] = field(default_factory=dict)
