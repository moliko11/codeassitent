from dataclasses import dataclass

from .prompts import DEFAULT_SYSTEM_PROMPT

@dataclass
class AgentConfig:
    # 系统提示词：定义 Agent 的行为契约，作为 messages 的第一条注入。
    # 默认与 agentloop 控制流对齐（见 prompts.py）；传空串可禁用。
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    model: str = "deepseek-v4-pro"
    temperature: float = 0.7
    max_tokens: int = 500
    max_steps: int = 5
    enable_tools: bool = True
    max_consecutive_tool_failures: int = 3