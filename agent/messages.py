# 对话角色枚举
from dataclasses import dataclass, field
from typing import Any, Literal

# ====================== 全局枚举定义 ======================
Role = Literal["system", "user", "assistant", "tool"]


# Agent 运行状态枚举（可序列化）

AgentStatus = Literal[
    "created",        # 已创建未启动
    "running",        # 运行中
    "waiting_tool",   # 等待工具执行
    "waiting_approval", # 等待人工审批
    "completed",      # 正常完成
    "failed",         # 运行失败
    "cancelled",      # 主动取消
    "max_steps_exceeded" # 超过最大步数限制
]

# 内容块类型（精细化消息结构使用）
ContentType = Literal["text", "image", "tool_use", "tool_result", "reasoning"]


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