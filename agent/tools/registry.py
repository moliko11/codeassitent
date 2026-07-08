# 工具注册表与执行器
import traceback

import jsonschema
from jsonschema.exceptions import ValidationError
# from pydantic import ValidationError

from .formatter import ToolResultFormatter

from .defs import Tool, ToolCall, ToolResult, ToolSpec
# import jsonschema

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


# 模块级默认注册表实例：@tool 装饰器向它注册
registry = ToolRegistry()


def tool(name, description, input_schema, examples=None, returns=""):
    def decorator(func):
        registry.register(Tool(
            tool_spec=ToolSpec(name=name, description=description,
                               input_schema=input_schema,
                               examples=examples or [], returns=returns),
            handler=func,
        ))
        return func
    return decorator


class ToolExecutor:
    def __init__(self, registry: ToolRegistry,formatter=None):
        self.registry = registry
        self.formatter=formatter or ToolResultFormatter()  # 默认格式化器

    def execute(self, call: ToolCall) -> ToolResult:
       
         # 1. 工具是否存在
        try:
            tool = self.registry.get_tool(call.tool_name)
        except Exception as e:
            return self._finalize(ToolResult(
                call_id=call.call_id, tool_name=call.tool_name, ok=False,
                error={"type": "ToolNotFound", "message": str(e), "retryable": False},
                meta=call.meta,
            ))
            # 2. 前置 Schema 校验（强制门禁）
        try:
            jsonschema.validate(
                instance=call.arguments,
                schema=tool.tool_spec.input_schema
            )
        except jsonschema.ValidationError as e:
            # 校验失败：返回结构化错误，不抛异常
              return self._finalize(ToolResult(
                call_id=call.call_id, tool_name=call.tool_name, ok=False,
                error={"type": "SchemaValidationError",
                       "message": e.message,
                       "field": list(e.absolute_path),
                       "retryable": False},
                meta=call.meta,
            ))
        # 3. 执行工具 handler
        try:
            result_data = tool.handler(**call.arguments)
            # 4. 返回成功结果
            return self._finalize(ToolResult(
            call_id=call.call_id, tool_name=call.tool_name, ok=True,
            data=result_data, meta=call.meta,
        ))
        except Exception as e:
            return self._finalize(ToolResult(
                call_id=call.call_id, tool_name=call.tool_name, ok=False,
                error={"type": type(e).__name__, "message": str(e),
                       "traceback": traceback.format_exc(), "retryable": False},
                meta=call.meta,
            ))

    def _finalize(self, result: ToolResult) -> ToolResult:
        """统一设 text（结构化 + 压缩），由 formatter 完成。"""
        result.text = self.formatter.format(result)
        return result
    
    def execute_many(self, calls: list[ToolCall], timeout=None) -> list[ToolResult]:
        """并行执行多个 tool_calls。有 depends_on 时按 DAG 层级并发。"""
        # 无依赖：全部并行
        if not any(c.depends_on for c in calls):
            return self._parallel(calls, timeout)

        # 有依赖：按 DAG 层级执行
        return self._dag_execute(calls, timeout)
    

    def _parallel(self, calls, timeout):
        """并行执行一组无依赖的 tool_calls"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        results = []
        with ThreadPoolExecutor(max_workers=min(len(calls), 8)) as pool:
            fut_map = {pool.submit(self.execute, c): c for c in calls}
            for fut in fut_map:
                try:
                    results.append(fut.result(timeout=timeout))
                except FuturesTimeout:
                    results.append(self._finalize(ToolResult(
                        call_id=fut_map[fut].call_id,
                        tool_name=fut_map[fut].tool_name,
                        ok=False,
                        error={"type": "StepTimeout", "message": f"工具执行超时（{timeout}s）", "retryable": True},
                        meta=fut_map[fut].meta,
                    )))
        return results
    
    def _dag_execute(self, calls: list[ToolCall], timeout=None) -> list[ToolResult]:
        """按 DAG 层级执行 tool_calls，支持 depends_on"""
        # 1. 构建 call_id -> ToolCall 映射
        by_id = {c.call_id: c for c in calls}
        done_ids: set[str] = set()
        results: list[ToolResult] = []
        remaining = list(calls)
        while remaining:
            # 本层：依赖都已完成的
            layer = [c for c in remaining if all(d in done_ids for d in c.depends_on)]
            if not layer:
                # 有环：剩余的强制执行（防死锁）
                layer = remaining
            layer_results = self._parallel(layer, timeout)
            results.extend(layer_results)
            done_ids.update(c.call_id for c in layer)
            remaining = [c for c in remaining if c.call_id not in done_ids]
        return results