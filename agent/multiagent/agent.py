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


def subagent_result_text(state: AgentState) -> str:
    """子 agent 最终结果文本:有 final_response 用其文本;否则给失败原因。

    对齐 CC 通知带 <status>(completed/failed/stopped):子 agent 撞 max_steps 或异常退出时
    final_response 为 None,若只回空串,主 agent 会拿空结果"猜小弟没返回"、卡住等结果。
    这里把 status/步数/错误回填成文本,主 agent 读文本即知子 agent 未完成,自行兜底处理。
    2026-08-07 新增,解决"子 agent 一直不返回导致主 agent 卡住"(见 docs/topics/session-issue-analysis.md)。
    """
    if state.final_response is not None:
        return state.final_response.text
    status = state.status
    steps = state.step_index or len(state.steps)
    err = state.error
    suffix = f", error={err}" if err else ""
    return (f"[子 agent 未完成] status={status}, steps={steps}{suffix}。"
            f"子 agent 没有输出最终回答,请主 agent 自行兜底处理该子任务。")


def subagent_status(state: AgentState) -> str:
    """子 agent 完成状态,对齐 CC 通知的 <status>(completed/failed/killed/stopped)。

    final_response 非 None = 有最终回答 = completed;否则把内部状态映射到 CC 三态:
    max_steps_exceeded -> failed(没干完)、cancelled -> stopped(被停)、failed -> failed。
    2026-08-07 新增:通知文本带结构化 status,主 agent 一眼知道子 agent 成败(不用读长文本猜)。
    """
    if state.final_response is not None:
        return "completed"
    return {"max_steps_exceeded": "failed", "cancelled": "stopped"}.get(state.status, state.status)


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
        #    config 覆盖 allowed_tools=self.tools(权限白名单);state 独立(子 AgentState,不共享父)。
        #    子 agent 事件不打印由 StreamingPrinter 过滤(_runtime_state.agent_id 非 None 即跳过),
        #    sink 链路保留:子 agent span 照常进父 tracer/主 trace(带 agent_id,题17 多 Agent tracing)。
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
