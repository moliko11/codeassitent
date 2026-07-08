# 运行时上下文容器：组装 Agent 一次执行所需的全部依赖
# 单独成层，避免 messages.py 反向依赖 state / Adapter 等上层模块
from dataclasses import dataclass, field

from .adapters.base import BaseModelAdapter
from .config.config import AgentConfig
from .core.state import AgentState
from .tools.registry import ToolExecutor, ToolRegistry
from .streaming.sink import EventSink, NullSink


@dataclass
class RuntimeContext:
    registry: ToolRegistry
    tool_executor: ToolExecutor
    model_adapter: BaseModelAdapter
    config: AgentConfig
    state: AgentState
    sink: EventSink = field(default_factory=NullSink)
