# agent/config/loader.py —— 集中加载 code/config/*.yaml 的中央加载器
#
# 覆盖优先级：Python dataclass 默认 < YAML < 环境变量(仅 provider 的 api_key/base_url/model 与
# AGENT_CONFIG_DIR/AGENT_PROVIDER 走 env；数值/开关类参数不做 env 覆盖)。
# 缺 YAML = 纯 Python 默认值：任何 yaml 缺失/某 key 缺失回落现有 dataclass 默认，
# code/config/ 不存在时整个系统行为与现状完全一致（不破坏 30 处 AgentConfig() 调用 + 测试）。
#
# 已知不一致（loader 只读不改，避免破坏测试）：
# - AgentState.max_steps=5 vs AgentConfig.max_steps=25：装配点显式 AgentState(max_steps=config.max_steps)，
#   5 只是裸构造默认。别用 YAML 动 AgentState。
# - builder 注入召回 top_k 由 context.yaml memory_recall_top_k 控制；store 直调 recall 默认由
#   memory.yaml recall_top_k 控制（历史遗留的两套旋钮，这里显式化）。
import os
from pathlib import Path

import yaml

from .config import AgentConfig

# code/config/ 目录：仿 provider.py 的 parents[2] 模式（agent/config/loader.py -> code/）
_BASE = Path(__file__).resolve().parents[2]

_SECTIONS = ("agent", "provider", "reliability", "context", "memory",
             "multiagent", "guardrails", "tools")

# 模块级缓存：首次 get_section() 时全量读一次；clear_cache() 供测试改 yaml 后重新加载/热重载。
_CACHE: dict[str, dict] | None = None


def config_dir() -> Path:
    """配置目录：AGENT_CONFIG_DIR env 优先，缺省 code/config/。"""
    return Path(os.environ.get("AGENT_CONFIG_DIR") or (_BASE / "config"))


def clear_cache() -> None:
    """清空模块级缓存（测试改 yaml 后重新加载 / 热重载）。"""
    global _CACHE
    _CACHE = None


def get_section(name: str) -> dict:
    """读某配置文件内容(dict)。文件缺失/为空 -> 空 dict(回落 Python 默认)。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_all()
    return _CACHE.get(name) or {}


def _load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    d = config_dir()
    for name in _SECTIONS:
        p = d / f"{name}.yaml"
        if not p.exists():
            out[name] = {}
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise ValueError(f"config/{name}.yaml 解析失败: {e}") from e
        out[name] = data if isinstance(data, dict) else {}
    return out


# ─────────────────── agent ───────────────────

def build_agent_config(overrides: dict | None = None) -> AgentConfig:
    """从 agent.yaml 构造 AgentConfig。未知 key 过滤掉(防 YAML 拼错 key 报 TypeError)。

    overrides 叠加在 YAML 之上(如装配点传 {"model": pc.model} 让 provider 模型覆盖)。
    system_prompt 不进 YAML(内容在 prompts.py,DEFAULT_SYSTEM_PROMPT 有测试断言文字),
    此字段永远用 Python 默认。exit_words 非 dataclass 字段,由 exit_words() 单独读。
    """
    cfg = get_section("agent")
    known = set(AgentConfig.__dataclass_fields__)
    kwargs = {k: v for k, v in cfg.items() if k in known and k != "system_prompt"}
    if overrides:
        kwargs.update({k: v for k, v in overrides.items() if k in known})
    return AgentConfig(**kwargs)


def exit_words() -> list[str]:
    """REPL 退出词(agent.yaml exit_words)。缺省 ["exit", "quit"]。"""
    return list(get_section("agent").get("exit_words") or ["exit", "quit"])


# ─────────────────── provider ───────────────────

def default_provider() -> str:
    """默认 provider 优先级: AGENT_PROVIDER env > provider.yaml default > "ark"(向后兼容)。"""
    return os.environ.get("AGENT_PROVIDER") or get_section("provider").get("default") or "ark"


def build_provider_config(provider: str | None = None) -> "ProviderConfig":
    """构造 provider 配置(api_key 只从 env 读)。委托 provider.load_provider_config 单一实现。"""
    from .provider import load_provider_config
    return load_provider_config(provider)


# ─────────────────── reliability ───────────────────

def build_retry_policy():
    """RetryPolicy(reliability.yaml retry 段)。"""
    from ..reliability.retry import RetryPolicy
    cfg = get_section("reliability").get("retry") or {}
    return RetryPolicy(
        max_attempts=cfg.get("max_attempts", 3),
        base_delay=cfg.get("base_delay", 0.5),
        max_delay=cfg.get("max_delay", 10.0),
        jitter=cfg.get("jitter", 0.1),
    )


def build_breaker_config():
    """BreakerConfig(reliability.yaml breaker 段)。"""
    from ..reliability.breaker import BreakerConfig
    cfg = get_section("reliability").get("breaker") or {}
    return BreakerConfig(
        failure_threshold=cfg.get("failure_threshold", 5),
        recovery_timeout=cfg.get("recovery_timeout", 10.0),
        half_open_max=cfg.get("half_open_max", 1),
    )


def build_tool_executor_params() -> dict:
    """ToolExecutor 可接受 kwargs(reliability.yaml)。audit disabled -> audit_logger=None。

    retry_mode 缺省 "runtime_retry"(主入口装配默认,同原 main());库级 ToolExecutor 默认仍 llm_retry。
    audit log_path 空 -> 回落 audit_path()(persist/audit.jsonl),集中在这处理,消灭两处重复。
    """
    from ..reliability.idempotency import IdempotencyStore
    from ..reliability.audit import AuditLogger
    from ..persist.paths import audit_path
    rel = get_section("reliability")
    ex = rel.get("execution") or {}
    audit = rel.get("audit") or {}
    audit_logger = None
    if audit.get("enabled", True):
        log_path = audit.get("log_path") or str(audit_path())
        audit_logger = AuditLogger(log_path=log_path)
    return {
        "retry_policy": build_retry_policy(),
        "retry_mode": ex.get("retry_mode", "runtime_retry"),
        "breaker_config": build_breaker_config(),
        "idempotency_store": IdempotencyStore(),
        "audit_logger": audit_logger,
        "parallelism": ex.get("parallel_semaphore", 8),
        "max_workers": ex.get("max_workers", 1),
        "result_summary_chars": ex.get("result_summary_chars", 80),
    }


# ─────────────────── context ───────────────────

def build_context_builder_params() -> dict:
    """ContextBuilder 可接受 kwargs(context.yaml builder 段)。

    不含 context_budget:装配点用 config.context_budget(agent.yaml),避免两个源打架。
    """
    cfg = get_section("context").get("builder") or {}
    return {
        "tool_result_threshold": cfg.get("tool_result_threshold", 2000),
        "keep_recent": cfg.get("keep_recent", 5),                    # 对齐 CC keepRecent=5
        "keep_recent_turns": cfg.get("keep_recent_turns", 4),
        "memory_recall_top_k": cfg.get("memory_recall_top_k", 3),
        "gap_threshold_minutes": cfg.get("gap_threshold_minutes", 60),  # 对齐 CC gapThresholdMinutes(短会话不清)
    }


# ─────────────────── memory ───────────────────

def build_memory_params() -> dict:
    """MemoryStore 可接受 kwargs(memory.yaml)。"""
    cfg = get_section("memory")
    return {
        "recall_top_k": cfg.get("recall_top_k", 5),
        "index_file": cfg.get("index_file", "MEMORY.md"),
    }


# ─────────────────── multiagent ───────────────────

def build_multiagent_params() -> dict:
    """OrchestratorAgent 可接受 kwargs(multiagent.yaml)。

    当前无主入口消费(集成脚本保持直接构造,按用户决策);loader 提供供需要时采纳。
    """
    cfg = get_section("multiagent").get("orchestrator") or {}
    return {"max_handoffs": cfg.get("max_handoffs", 5)}


# ─────────────────── guardrails ───────────────────

def load_guardrail_names() -> list[str]:
    """guardrails.yaml enabled 清单；缺省 = 现 4 个默认 guard(权限三 guard 已移到 can_use_tool)。"""
    return list(get_section("guardrails").get("enabled") or [
        "prompt_injection", "pii", "indirect_injection", "pii_tool_result",
    ])


def build_guardrail_runner(names: list[str] | None = None):
    """按 guard 名装配 GuardrailRunner(guardrails/factory.py)。未知名 raise(fail-fast)。"""
    from ..guardrails.factory import build_guardrail_runner as _build
    return _build(names)
