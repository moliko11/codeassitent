from dataclasses import dataclass

from ..prompts import DEFAULT_SYSTEM_PROMPT

@dataclass
class AgentConfig:
    # 系统提示词：定义 Agent 的行为契约，作为 messages 的第一条注入。
    # 默认与 agentloop 控制流对齐（见 prompts.py）；传空串可禁用。
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    model: str = "deepseek-v4-pro"
    temperature: float = 0.7
    max_tokens: int = 5000
    max_steps: int = 5
    enable_tools: bool = True
    max_consecutive_tool_failures: int = 3 # 连续工具调用失败次数，超过则强制结束循环
    soft_stop_threshold: int = 3  # 连续重复调用相同工具+参数的次数，达此值注入软终止提醒（继续运行，不强制结束）
    step_timeout: float = 30.0  # 每轮 Agent 循环的超时时间（秒），超过则抛出 StepTimeout 异常


"""
time.perf_counter() + config.step_timeout 记录。实际超时判断用 step_timeout，
deadline 主要做记录（精确版可算剩余时间 max(0, deadline - now) 传给后续调用）
"""