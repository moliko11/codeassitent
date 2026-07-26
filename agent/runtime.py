# 运行时上下文容器：组装 Agent 一次执行所需的全部依赖
# 单独成层，避免 messages.py 反向依赖 state / Adapter 等上层模块
from dataclasses import dataclass, field
from typing import Optional

from .adapters.base import BaseModelAdapter
from .config.config import AgentConfig
from .context.builder import ContextBuilder
from .memory.store import MemoryStore
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
    persist: bool = False   # 阶段 5：True 时 agentloop 建 Persister 落盘 transcript

    context_builder: Optional[ContextBuilder] = None  # 阶段 6：None 时 agentloop 从 config 现场构造
    memory_store: Optional[MemoryStore] = None        # 步6:长期记忆(None=不召回)
