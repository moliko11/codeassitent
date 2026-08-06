import json
from .defs import ToolResult


class ToolResultFormatter:
    """把 ToolResult 格式化成回填给模型的 text：结构化错误 + 成功结果压缩。"""

    def __init__(self, strategy: str = "none", max_length: int = 2000):  # 默认 none:不截断,大结果交给 ToolResultBudget 落盘(对齐 cc)
        self.strategy = strategy
        self.max_length = max_length

    def format(self, result: ToolResult) -> str:
        if not result.ok:
            return self._format_error(result)
        return self._compress(self._format_success(result))

    def _format_success(self, result):
        return json.dumps(
            {"ok": True, "tool": result.tool_name, "data": result.data},
            ensure_ascii=False,
        )

    def _format_error(self, result):
        err = result.error or {}
        return json.dumps({
            "ok": False,
            "error_type": err.get("type", "UnknownError"),
            "message": err.get("message", ""),
            "suggestion": self._suggest(err),
            "retryable": err.get("retryable", False),
        }, ensure_ascii=False)

    def _suggest(self, err):
        t = err.get("type", "")
        if t == "SchemaValidationError":
            return f"参数校验失败：{err.get('message', '')}。请按 schema 修正参数。"
        if t == "StepTimeout":
            return "工具执行超时，可重试或换一种方法。"
        if t == "ToolTimeout":
            return "工具执行超时，可重试或换一种方法。"
        if t == "CircuitOpen":
            return "工具执行失败，请换一种方法或基于已有信息作答。"
        if t == "Cancelled":
            return "操作被取消，可重试或换一种方法。"
        if t in ("KeyError", "TypeError", "ValueError"):
            return "参数缺失或类型不对，请检查必填字段。"
        return "工具执行失败，请换一种方法或基于已有信息作答。"

    def _compress(self, text: str) -> str:
        if self.strategy == "none":
            return text  # 不压缩:大结果交给 ToolResultBudget 落盘(对齐 cc,无损)
        if len(text) <= self.max_length:
            return text
        if self.strategy == "truncate":
            return text[:self.max_length] + f"...（已截断，共 {len(text)} 字符，如需更多请分页）"
        # summarize/paginate 不实现:对齐 CC 不截断,大结果交 ToolResultBudget 无损落盘(CLAUDE.md 约定)
        return text
