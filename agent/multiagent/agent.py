# multiagent/agent.py - Agent 抽象(阶段10,题1/2)
# Agent = 一个可独立 loop 的单元(role/tools/config/runtime + async run)。
# 复用 async _run_turn(通过 RuntimeContext),不重写 loop。对标 CC runAgent 递归 query()。
# 子 agent 隔离:dataclasses.replace 出独立 runtime(共享 registry/adapter/sink,独立 config+state),
# 不污染父;messages 继承父的(简化,§8.3;CC 克隆 toolUseContext 留 TODO)。
import uuid
from dataclasses import dataclass, field, replace
from typing import Optional

from ..core.state import AgentState
from ..runtime import RuntimeContext
from ..config.config import AgentConfig
from ..tools import _runtime_state
from .blackboard import Blackboard


@dataclass
class Agent:
    """一个可独立 loop 的 Agent 单元。

    role:   "orchestrator" / "search_worker" / "coder" / "reviewer" 等
    tools:  allowed_tools 白名单(权限隔离,题16);空 list=全允许(默认,但 handoff 特权不自动放开)
    config: 该 agent 的 AgentConfig(model/mode/max_steps 等)
    runtime:复用的 RuntimeContext(共享 model_adapter/registry/tool_executor/sink)
    """
    role: str
    tools: list[str]
    config: AgentConfig
    runtime: RuntimeContext
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    async def run(self, task: str, blackboard: Optional[Blackboard] = None, persister=None) -> AgentState:
        """执行任务:子 runtime(独立 config+state)+ blackboard 注入 + 调 _run_turn。

        返回子 AgentState(含 final_response)。persister=None 不落盘(§8.3);传 persister 则子 agent
        事件落该 transcript(Task 工具传主 persister + agent_id="subagent",web 可展示子 agent 流)。
        """
        from ..agentloop import _run_turn  # 延迟导入,避免 agentloop <-> multiagent 循环引用

        # commit 10:设当前 agent role(多 Agent tracing;Tracer 把它写进 span attrs)
        _runtime_state.agent_id.set(self.role)

        # 1. 子 agent 隔离:replace 出独立 runtime(共享 registry/adapter/sink,独立 config+state)
        #    config 覆盖 allowed_tools=self.tools(权限白名单);state 独立(子 AgentState,不共享父)
        child_config = replace(self.config, allowed_tools=self.tools)
        child_state = AgentState(max_steps=self.config.max_steps)
        child_state.messages = list(self.runtime.state.messages)  # 继承父 messages(简化)
        child_runtime = replace(self.runtime, config=child_config, state=child_state)

        # 2. blackboard 快照注入 task(模型可见共享状态);空 blackboard 不注入
        task_msg = task
        if blackboard is not None and blackboard.data:
            task_msg = f"{task}\n\n[共享黑板]\n{blackboard.snapshot()}"

        # 3. 复用 _run_turn(react/plan_execute/workflow 由 child_config.mode 决定)
        return await _run_turn(task_msg, child_state, child_runtime, persister=persister)
