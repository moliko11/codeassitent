# tools 子包：数据模型(defs) + 注册与执行(registry) + 内置工具(builtin)
from .defs import Tool, ToolCall, ToolResult, ToolSpec
from .registry import ToolExecutor, ToolRegistry, registry, tool
from . import builtin  # 触发内置工具注册到 registry
from . import test_tools  # 触发测试工具注册（tavily/读文件/grep）到 registry
from . import FileReadTool    # 触发 read 注册
from . import FileEditTool    # 触发 edit 注册
from . import FileWriteTool   # 触发 write 注册
from . import BashTool        # 触发 bash 注册
from . import GlobTool        # 触发 glob 注册
from . import GrepTool        # 触发 grep 注册
from . import WebSearchTool   # 触发 web_search 注册(步3)
from . import WebFetchTool    # 触发 web_fetch 注册(步3)
from . import TodoWriteTool   # 触发 todo_write 注册(步4)
from . import AskUserQuestionTool  # 触发 ask_user 注册(步4)

__all__ = [
    "Tool", "ToolCall", "ToolResult", "ToolSpec",
    "ToolExecutor", "ToolRegistry", "registry", "tool",
]
