# 运行时上下文容器：组装 Agent 一次执行所需的全部依赖
# 单独成层，避免 messages.py 反向依赖 state / Adapter 等上层模块
from dataclasses import dataclass

from .tools import ToolRegistry, ToolExecutor
from .Adapter import OpenAIAdapter
from .config import AgentConfig
from .state import AgentState


@dataclass
class RuntimeContext:
    registry: ToolRegistry
    tool_executor: ToolExecutor
    model_adapter: OpenAIAdapter
    config: AgentConfig
    state: AgentState
