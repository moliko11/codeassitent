# agent/bootstrap.py - 组合根(Composition Root):装配共享运行时依赖一次,CLI/web 共用
#
# 之前 agentloop.main() 与 chatweb/backend/server.py 各装配一遍(adapter/config/guardrail/
# tool_executor/tools 参数/memory/tools 注册),加一行改两处、必然漂移。本模块是唯一装配点:
#   - CLI:main() 调 build_runtime() 后进 run_agent_loop
#   - web:server.py 模块级调 build_runtime(confirmer=web_confirmer)
# 每进程装配一次,结果当模块级共享单例(跨 session/进程复用)。
#
# 依赖方向:bootstrap -> {config, tools, memory, agentloop(_track_edit_callback)},
# 反向不成立(agentloop/config 不 import bootstrap),无循环。
from dataclasses import dataclass

from .config.provider import load_provider_config, make_adapter
from .config.loader import (
    build_agent_config, build_guardrail_runner, build_memory_params,
    build_tool_executor_params, get_section,
)
from .tools.registry import ToolExecutor, ToolRegistry
from .tools.settings import configure_tools
from .tools.memory_tool import make_save_memory_tool
from .tools.task_tool import make_task_tool
from .memory import MemoryStore
from .persist.paths import memory_dir
from .agentloop import _track_edit_callback


@dataclass
class Runtime:
    """一次装配的共享运行时依赖(CLI/web 复用;跨 session 不重建)。"""
    registry: ToolRegistry
    model_adapter: object
    config: object
    guardrail_runner: object
    tool_executor: ToolExecutor
    memory_store: MemoryStore


def build_runtime(*, confirmer=None) -> Runtime:
    """组合根:装配共享运行时依赖一次。

    - provider(config/provider.py 按 AGENT_PROVIDER/env 读 key/base_url/model,导入即 load_dotenv)
    - config:provider 的 model 覆盖 AgentConfig 默认(否则发给 API 的 model 形同虚设)
    - guardrail_runner + ToolExecutor(可靠性四件套 + HITL confirmer)
    - tools.yaml 参数(configure_tools)+ memory + save_memory/task 工具注册
    confirmer:缺省 None -> ToolExecutor 回落 cli_confirmer(CLI);web 传 web_confirmer(HITL 弹窗)。
    """
    import agent.tools   # @tool 装饰器把 getnowtime 注册到了 tools 子包的默认 registry
    registry = agent.tools.registry
    pc = load_provider_config()
    if not pc.api_key:
        raise RuntimeError(f"未设置 {pc.provider} 的 API key,请在 code/.env 配置对应 key/base_url/model")
    model_adapter = make_adapter(pc)
    config = build_agent_config({"model": pc.model})
    # 阶段8: GuardrailRunner + 默认 Guard(guardrails.yaml 控制启用清单;未知 guard 名 fail-fast)
    guardrail_runner = build_guardrail_runner()
    # 可靠性四件套 + 执行参数(reliability.yaml;audit disabled -> audit_logger=None)。
    tool_executor = ToolExecutor(
        registry,
        before_mutation=_track_edit_callback,   # Phase 2 §2.5:Edit/Write 写盘前备份(file_history 版本链条)
        guardrail_runner=guardrail_runner,
        config=config,
        confirmer=confirmer,          # 缺省 None -> ToolExecutor 回落 cli_confirmer(同旧 main)
        **build_tool_executor_params(),
    )
    # 工具超时/截断参数(tools.yaml),给 @tool handler 的 t() 查找用
    configure_tools(get_section("tools"))
    # 步6:创建 memory_store + 注册 save_memory 工具(闭包捕获 store)
    memory_store = MemoryStore(memory_dir(), **build_memory_params())
    registry.register(make_save_memory_tool(memory_store))
    # 阶段10:Task 工具(主 agent 派子 agent,CC 小弟模型);已注册则跳过
    try:
        registry.register(make_task_tool())
    except Exception:
        pass
    return Runtime(
        registry=registry, model_adapter=model_adapter, config=config,
        guardrail_runner=guardrail_runner, tool_executor=tool_executor,
        memory_store=memory_store,
    )
