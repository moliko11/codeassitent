# 工具数据模型（纯数据，无执行逻辑，无业务依赖，处于最底层）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolSpec:
    """工具声明：仅包含给大模型感知的定义（无执行逻辑）"""
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema 入参规范
    examples: list[dict[str, Any]] = field(default_factory=list)  # 示例调用
    returns:str=""
    meta: dict[str, Any] = field(default_factory=dict)
    fallback_tool_name: str | None = None # TODO: 失败时 fallback 到另一个工具（如：调用模型失败时 fallback 到本地工具）
    idempotent: bool = False # TODO: 是否幂等（同一 call_id 重复调用不会有副作用），用于幂等去重缓存

@dataclass
class Tool:
    """工具定义：包含执行逻辑"""
    tool_spec: ToolSpec
    handler: Callable[..., Any]
    meta: dict[str, Any] = field(default_factory=dict)

    def run(self, *args, **kwargs):
        return self.handler(*args, **kwargs)


@dataclass
class ToolCall:
    call_id: str            # 调用ID
    tool_name: str          # 工具名称
    arguments: dict[str, Any]  # 工具调用参数
    raw: dict[str, Any] | None = None      # 原始调用数据
    meta: dict[str, Any] = field(default_factory=dict)  # 元数据
    depends_on: list[str] = field(default_factory=list)  # 依赖的其他 tool_call_id 列表


@dataclass
class ToolResult:
    call_id: str            # 调用ID
    tool_name: str          # 工具名称
    ok: bool                # 调用是否成功
    data: dict[str, Any] = field(default_factory=dict)   # 调用结果数据
    error: dict[str, Any] | None = None     # 调用错误信息
    meta: dict[str, Any] = field(default_factory=dict)   # 元数据
    text: str | None = None  # 调用结果文本

