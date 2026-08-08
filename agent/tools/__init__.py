# tools 子包：数据模型(defs) + 注册与执行(registry) + 内置工具(builtin)
#
# 注册入口(统一约定,见 bootstrap.py):
#   1. 静态工具(@tool 装饰器):import 本包即注册到默认 registry(下表)。生产工具集固定。
#   2. 动态工具(make_*_tool 工厂,需闭包/运行时依赖):在 agent/bootstrap.build_runtime 显式
#      registry.register(make_*_tool(...)),不进 import 副作用。
#   测试工具(sample_tools,标注"仅测试用")不再自动注册进生产——需要时显式
#     `from agent.tools import sample_tools`(import 触发其 @tool 注册)。
from .defs import Tool, ToolCall, ToolResult, ToolSpec
from .registry import ToolExecutor, ToolRegistry, registry, tool
from . import builtin  # 触发内置工具注册(getnowtime)到 registry
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
