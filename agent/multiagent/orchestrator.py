# multiagent/orchestrator.py - Orchestrator/Worker/Reviewer(阶段10,题4/5/6/7)
# OrchestratorAgent:接收任务,跑一轮,根据模型输出(是否调 handoff 工具)决定 delegate 给 worker / 完成。
# WorkerAgent:专职 worker(search/coder/data),复用 Agent.run。
# ReviewerAgent:Reviewer(stage7 Critic 升级版),commit 7 占位,评估逻辑留 TODO。
# 对标 CC:coordinator(system prompt + agent 工具白名单 + subagent 隔离);我们用 OrchestratorAgent + allowed_tools。
from typing import Optional

from .agent import Agent
from .blackboard import Blackboard
from .handoff import detect_handoff
from ..core.state import AgentState
from ..runtime import RuntimeContext


class OrchestratorAgent(Agent):
    """接收任务,决定自己处理 / handoff 给 worker / 完成。

    handoff 循环:跑一轮 -> detect_handoff 检查模型是否要 handoff ->
      要:delegate 给目标 worker,结果写 blackboard,带着 blackboard 继续原任务(下一轮)
      不要:模型 FINISH,返回
    max_handoffs 上限防无限转交(题15);转交历史去重(同任务 A<->B 反复弹)留 commit 10。
    """

    def __init__(self, runtime: RuntimeContext, workers: list[Agent],
                 max_handoffs: int = 5, config=None):
        # orchestrator 暂不直接调 worker 工具(tools=[]);commit 8 注册 handoff 工具后改为 ["handoff"]
        super().__init__(role="orchestrator", tools=[],
                         config=config or runtime.config, runtime=runtime)
        self.workers: dict[str, Agent] = {w.role: w for w in workers}
        self.max_handoffs = max_handoffs

    async def run(self, task: str, blackboard: Optional[Blackboard] = None) -> AgentState:
        blackboard = blackboard or Blackboard()
        handoff_count = 0
        current_task = task
        state: Optional[AgentState] = None
        while handoff_count < self.max_handoffs:
            # 跑一轮(orchestrator 自己的 _run_turn),detect_handoff 看是否要 handoff
            state = await super().run(current_task, blackboard)
            handoff = detect_handoff(state)
            if handoff is None:
                return state  # 模型没要 handoff -> 完成
            target = self.workers.get(handoff.to_role)
            if target is None:
                return state  # 无效 handoff 目标 -> 结束(防指向不存在的 agent)
            handoff_count += 1
            # delegate 给目标 worker,结果写 blackboard(其他 agent 下一轮可见)
            worker_state = await target.run(handoff.context, blackboard)
            await blackboard.set(target.role,
                                 getattr(worker_state.final_response, "text", "") or "")
            # 带着blackboard 继续;原任务附在 current_task 里防 orchestrator 遗忘
            current_task = f"[{target.role} 已完成,结果已写入 blackboard] 继续原任务:{task}"
        return state  # 超 max_handoffs -> 终止(防无限转交)


class WorkerAgent(Agent):
    """专职 worker(search/coder/data)。复用 Agent.run,无额外逻辑。"""
    pass


class ReviewerAgent(Agent):
    """Reviewer:stage7 Critic 升级版,评估其他 agent 的结果。

    commit 7 占位(复用 Agent.run);评估/打分逻辑(对齐 Critic.evaluate_result)留 TODO。
    """
    pass
