# multiagent - 多 Agent 协作(阶段10)
# 依赖只能向下:multiagent 依赖 core + runtime + agentloop(_run_turn);agentloop 不依赖 multiagent。
# 入口在 main 构造 Orchestrator(或保留单 agent)。
from .agent import Agent
from .blackboard import Blackboard
from .handoff import Handoff, detect_handoff
from .orchestrator import OrchestratorAgent, WorkerAgent, ReviewerAgent
from .background import run_subagent_background, launch_background_subagent

__all__ = [
    "Agent", "Blackboard", "Handoff", "detect_handoff",
    "OrchestratorAgent", "WorkerAgent", "ReviewerAgent",
    "run_subagent_background", "launch_background_subagent",
]
