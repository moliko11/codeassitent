# tools 子包：数据模型(defs) + 注册与执行(registry) + 内置工具(builtin)
from .defs import Tool, ToolCall, ToolResult, ToolSpec
from .registry import ToolExecutor, ToolRegistry, registry, tool
from . import builtin  # 触发内置工具注册到 registry

__all__ = [
    "Tool", "ToolCall", "ToolResult", "ToolSpec",
    "ToolExecutor", "ToolRegistry", "registry", "tool",
]
