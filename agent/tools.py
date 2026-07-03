# 基础工具类
from __future__ import annotations

from dataclasses import dataclass, field
import traceback
from typing import Any, Callable, Dict

@dataclass
class ToolSpec:
    """工具声明：仅包含给大模型感知的定义（无执行逻辑）"""
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema 入参规范
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class Tool:
    """工具定义：包含执行逻辑"""
    tool_spec: ToolSpec
    handler: Callable[..., Any] # 工具处理函数
    meta: dict[str, Any] = field(default_factory=dict)

    def run(self, *args, **kwargs):
        return self.handler(*args, **kwargs)

@dataclass
class ToolCall:
    call_id: str #调用ID
    tool_name: str #工具名称
    arguments: dict[str, Any] #工具调用参数
    raw: dict[str, Any] | None = None #原始调用数据
    meta: dict[str, Any] = field(default_factory=dict) # 元数据
@dataclass
class ToolResult:
    call_id: str #调用ID
    tool_name: str #工具名称
    ok: bool #调用是否成功
    data: dict[str, Any] = field(default_factory=dict) #调用结果数据
    error: dict[str, Any] | None = None # 调用错误信息
    meta: dict[str, Any] = field(default_factory=dict)# 元数据
    text: str | None = None # 调用结果文本

class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
    def register(self, tool: Tool):
        name = tool.tool_spec.name
        if name in self.tools:
            raise ValueError(f"Tool with name '{name}' is already registered.")
        self.tools[name] = tool
    
    def get_tool(self, name: str) -> Tool:
        if name not in self.tools:
            raise ValueError(f"Tool with name '{name}' is not registered.")
        return self.tools[name]
    def list_tools(self) -> list[Tool]:
        return list(self.tools.values())


registry = ToolRegistry()


def tool(name: str, description: str, input_schema: Dict[str, Any]):
    def decorator(func):
        registry.register(
            Tool(
                tool_spec=ToolSpec(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                ),
                handler=func,
            )
        )
        return func
    return decorator

class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(self, call:ToolCall) -> ToolResult:
        try:
            tool = self.registry.get_tool(call.tool_name)
            result_data = tool.handler(**call.arguments)
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=True,
                data=result_data,
                meta=call.meta
            )
        except Exception as e:
        
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error={
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                    "retryable": False
                },
                meta={
                }
            )
@tool(
    name="getnowtime",
    description="获取当前时间",
    input_schema={
        "type": "object",
        "properties": {},
        "required": []
    }
)
def getnowtime():
    from datetime import datetime
    return datetime.now().isoformat()
    
