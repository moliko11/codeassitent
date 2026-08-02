# multiagent/orchestrator.py - Orchestrator/Worker/Reviewer(阶段10,题4/5/6/7)
# OrchestratorAgent:接收任务,跑一轮,根据模型输出(是否调 handoff 工具)决定 delegate 给 worker / 完成。
# WorkerAgent:专职 worker(search/coder/data),复用 Agent.run。
# ReviewerAgent:Reviewer(stage7 Critic 升级版),commit 7 占位,评估逻辑留 TODO。
# 对标 CC:coordinator(system prompt + agent 工具白名单 + subagent 隔离);我们用 OrchestratorAgent + allowed_tools。
import asyncio
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
        # orchestrator 只 handoff,不直接调 worker 工具(allowed_tools=["handoff"],权限隔离)
        super().__init__(role="orchestrator", tools=["handoff"],
                         config=config or runtime.config, runtime=runtime)
        self.workers: dict[str, Agent] = {w.role: w for w in workers}
        self.max_handoffs = max_handoffs
        # 按需注册 handoff 工具(工厂,对齐 make_save_memory_tool;不全局注册避免污染单 agent)
        if "handoff" not in runtime.registry.tools:
            from ..tools.handoff_tool import make_handoff_tool
            runtime.registry.register(make_handoff_tool())

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

    def launch_background(self, worker_role: str, task: str) -> asyncio.Task:
        """fire-and-forget 启动一个 worker 后台跑;完成时结果经 notify_queue 回主循环下轮注入。

        区别 serial handoff(await worker):background 不阻塞 orchestrator,worker 在 asyncio.Task
        里跑(contextvar 隔离),完成时 put (role, text) 到 runtime.notify_queue,主循环排干时注入。
        依赖 runtime.notify_queue(由 run_agent_loop 注入);None 则抛(无后台通道)。
        对标 CC runAsyncAgentLifecycle。何时调(模型决策)留 TODO:可加 launch_subagent 工具。
        """
        from .background import launch_background_subagent
        if self.runtime.notify_queue is None:
            raise RuntimeError("无 notify_queue:后台 subagent 需 run_agent_loop 注入通道")
        worker = self.workers.get(worker_role)
        if worker is None:
            raise KeyError(f"无 worker: {worker_role}")
        return launch_background_subagent(worker, task, self.runtime.notify_queue)


class WorkerAgent(Agent):
    """专职 worker(search/coder/data)。复用 Agent.run,无额外逻辑。"""
    pass


class ReviewerAgent(Agent):
    """Reviewer:stage7 Critic 升级版,评估其他 agent 的结果。

    commit 7 占位(复用 Agent.run);评估/打分逻辑(对齐 Critic.evaluate_result)留 TODO。
    """
    pass
