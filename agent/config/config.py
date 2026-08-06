from dataclasses import dataclass, field
from typing import Optional, Literal

from ..prompts import DEFAULT_SYSTEM_PROMPT

@dataclass
class AgentConfig:
    # 系统提示词：定义 Agent 的行为契约，作为 messages 的第一条注入。
    # 默认与 agentloop 控制流对齐（见 prompts.py）；传空串可禁用。
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    model: str = "deepseek-v4-pro"
    temperature: float = 0.7
    max_tokens: int = 30000
    max_steps: int = 25 # 最大循环步数，超过则强制结束循环（防止无限循环）
    enable_tools: bool = True
    max_consecutive_tool_failures: int = 3 # 连续工具调用失败次数，超过则强制结束循环
    soft_stop_threshold: int = 3  # 连续重复调用相同工具+参数的次数，达此值注入软终止提醒（继续运行，不强制结束）
    step_timeout: float = 200.0  # 每轮 Agent 循环的超时时间（秒），超过则抛出 StepTimeout 异常
    context_budget: Optional[int] = None  # 阶段 6：单次请求输入侧 token 预算(None=不限)。模型 window 减 max_tokens 再打折
    language: str = "中文"  # 动态提示词:语言段(对齐 cc language section),独立于静态核心
    include_git_info: bool = True  # 动态提示词:是否注入 git 仓库段(分支/remote,对齐 cc env_info 的 git 部分);False 跳过
    # ---- 阶段 7:Planning/ReAct/Workflow ----
    mode: Literal["react", "plan_execute", "workflow"] = "react"  # react=纯 agentic(默认,现状零改动);plan_execute=先规划再执行(可选);workflow=固定 DAG
    expose_reasoning: bool = True  # 是否把模型 thinking/reasoning 流式给用户(True=显示内部 CoT);对齐 CC expose_reasoning,控制 ThinkingDelta 渲染,不影响最终回答
    thinking_budget: Optional[int] = None  # thinking token 预算(None=不限/provider 不支持);透传 provider,不支持的字段静默忽略
    replan_every: int = 3  # plan_execute 模式:每 N 步调 Critic 评估计划漂移
    critic_enabled: bool = True  # plan_execute 模式:是否过 Critic 验收
    # ---- 阶段 10:多 Agent 权限隔离(题16)----
    # 空 list=全允许(默认,兼容单 agent);PermissionGuard(stage8)读它做白名单:非空时只放行列表内工具。
    # Agent.run 用 dataclasses.replace 把 self.tools 写进 child_config,实现 per-agent 工具隔离。
    allowed_tools: list[str] = field(default_factory=list)


"""
time.perf_counter() + config.step_timeout 记录。实际超时判断用 step_timeout，
deadline 主要做记录（精确版可算剩余时间 max(0, deadline - now) 传给后续调用）
"""