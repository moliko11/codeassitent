"""阶段8 真实 LLM 联调:验证 Guardrail 接入不破坏正常流程 + PII 脱敏生效。

用 DeepSeek + guardrail_runner(默认 5 个 Guard)。验证点:
  1. 正常输入通过 PromptInjectionGuard(不拦)
  2. 工具调用通过 before_tool(不拦)
  3. 最终回答过 PIIGuard:on_output 脱敏手机号 13812345678 -> 138****5678

运行(从 code/ 目录,3.12 venv):
    python stage8_integration.py
"""
import sys

from agent.config.config import AgentConfig
from agent.config.provider import load_provider_config, make_adapter
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.agentloop import agentloop, _track_edit_callback
from agent.runtime import RuntimeContext
from agent.core.state import AgentState
from agent.streaming.printer import StreamingPrinter
from agent.guardrails import (GuardrailRunner, PromptInjectionGuard, PermissionGuard,
    HighRiskGuard, PIIGuard, IndirectInjectionGuard)

import agent.tools  # 触发默认工具注册
from agent.tools import registry as default_registry
from agent.memory import MemoryStore
from agent.persist.paths import memory_dir
from agent.tools.memory_tool import make_save_memory_tool


def main():
    pc = load_provider_config("openai_compatible")  # DeepSeek
    if not pc.api_key:
        raise SystemExit("未设置 DEEPSEEK_API_KEY,请在 code/.env 配置")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    adapter = make_adapter(pc)
    registry = default_registry
    config = AgentConfig(model=pc.model, max_steps=5)
    guardrail_runner = GuardrailRunner()
    guardrail_runner.register(PromptInjectionGuard()) \
        .register(PermissionGuard()).register(HighRiskGuard()) \
        .register(PIIGuard()).register(IndirectInjectionGuard())
    tool_executor = ToolExecutor(registry, before_mutation=_track_edit_callback,
                                  guardrail_runner=guardrail_runner, config=config)
    memory_store = MemoryStore(memory_dir())
    registry.register(make_save_memory_tool(memory_store))

    state = AgentState(max_steps=5)
    ctx = RuntimeContext(
        registry=registry, tool_executor=tool_executor,
        model_adapter=adapter, config=config, state=state,
        sink=StreamingPrinter(expose_reasoning=False),
        guardrail_runner=guardrail_runner,
    )

    # 让模型输出含手机号,验证 PIIGuard on_output 脱敏
    task = "请输出一段包含手机号 13812345678 的示例客服短信文本"
    print(f"=== 任务:{task}\n")
    result = agentloop(task, ctx)

    final_text = getattr(result.final_response, "text", None) or ""
    print(f"\n=== 状态:{result.status} ===")
    print(f"=== 最终回答(应见 138****5678,不见 13812345678):\n{final_text} ===")
    print(f"=== 脱敏验证:含 13812345678(原)={'13812345678' in final_text};含 138****5678(脱敏)={'138****5678' in final_text} ===")


if __name__ == "__main__":
    main()
