# 对话消息数据模型（最底层，仅依赖 enums）
# 注意：本模块不依赖 state / Adapter / config 等上层，避免循环导入
from dataclasses import dataclass, field
from typing import Any

from .enums import Role, ContentType


@dataclass
class Message:
    """统一对话消息（精简版，通用推荐）"""
    role: Role
    content: Any  # 字符串｜结构化内容｜工具载荷
    meta: dict[str, Any] = field(default_factory=dict)  # 溯源、时间、标签等扩展信息

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
