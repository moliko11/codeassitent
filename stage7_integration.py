"""阶段7 真实 LLM 联调:验证 plan_execute 模式(Planner 产 Plan + subtask 执行 + Critic 验收)。

对照 stage6_integration.py。用 DeepSeek(openai_compatible)。
验证点:
  1. Planner 调 LLM 产 Plan(JSON,_parse_plan 容错)
  2. 每个 plan step 跑 _run_steps(subtask=True),FINISH 不 complete
  3. Critic 收尾 evaluate_result 被调
  4. 最终 state.status == completed,有最终回答

运行(从 code/ 目录,3.12 venv):
    python stage7_integration.py
"""
import sys

from agent.config.config import AgentConfig
from agent.config.provider import load_provider_config, make_adapter
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.agentloop import agentloop, _track_edit_callback
from agent.runtime import RuntimeContext
from agent.core.state import AgentState
from agent.streaming.printer import StreamingPrinter
from agent.memory import MemoryStore
from agent.persist.paths import memory_dir
from agent.tools.memory_tool import make_save_memory_tool

import agent.tools  # 触发默认工具注册(getnowtime 等)
from agent.tools import registry as default_registry


def main():
    pc = load_provider_config("openai_compatible")  # DeepSeek
    if not pc.api_key:
        raise SystemExit("未设置 DEEPSEEK_API_KEY,请在 code/.env 配置 DEEPSEEK_API_KEY/BASE_URL/MODEL")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    adapter = make_adapter(pc)
    registry = default_registry
    tool_executor = ToolExecutor(registry, before_mutation=_track_edit_callback)
    memory_store = MemoryStore(memory_dir())
    registry.register(make_save_memory_tool(memory_store))

    config = AgentConfig(
        mode="plan_execute",
        model=pc.model,
        max_steps=5,
        critic_enabled=True,
        replan_every=3,        # 2~3 步任务不触发中途 replan,只走收尾验收
        expose_reasoning=False,  # 隐藏 thinking,只看最终回答
    )
    state = AgentState(max_steps=5)
    ctx = RuntimeContext(
        registry=registry,
        tool_executor=tool_executor,
        model_adapter=adapter,
        config=config,
        state=state,
        sink=StreamingPrinter(expose_reasoning=False),
    )

    task = "用 getnowtime 工具查询当前时间,然后基于结果总结现在是一天中的什么时段(上午/下午/晚上)"
    print(f"=== 任务:{task}\n")
    result = agentloop(task, ctx)

    print(f"\n=== 最终状态:{result.status} ===")
    print(f"=== 最终回答:{getattr(result.final_response, 'text', None)} ===")
    print(f"=== steps 数:{len(result.steps)} ===")
    print(f"=== tool_history:{[(h.tool_name, h.ok) for h in result.tool_history]} ===")


if __name__ == "__main__":
    main()
