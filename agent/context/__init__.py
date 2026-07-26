# 阶段 6：上下文管理包。
# 调 LLM 前在这里组装/裁剪/压缩 messages，对齐 cc query.ts 的压缩管线入口。
from .auto_compact import auto_compact, make_summarizer
from .builder import ContextBuilder, BuildResult
from .budget import apply_tool_result_budget
from .counter import count_message_tokens, estimate_text_tokens
from .micro_compact import micro_compact

__all__ = [
    "ContextBuilder",
    "BuildResult",
    "apply_tool_result_budget",
    "micro_compact",
    "auto_compact",
    "make_summarizer",
    "count_message_tokens",
    "estimate_text_tokens",
]