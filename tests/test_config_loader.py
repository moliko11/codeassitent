"""config loader 验收测试：code/config/*.yaml -> agent/config/loader.py。

核心保证：
- 缺 YAML = 纯 Python 默认值(code/config/ 不存在时行为与现状完全一致)。
- 优先级 Python 默认 < YAML < env(仅 provider 的 api_key/base_url/model 与 AGENT_PROVIDER 走 env)。
- api_key 绝不从 YAML 读(只从 api_key_env 指定的环境变量)。

测试用 tmp 配置目录(monkeypatch AGENT_CONFIG_DIR + clear_cache),不碰真实 code/config/。
yaml 内容用 json.dumps 写(JSON 是 YAML 子集,pyyaml 可 safe_load)。

运行(从 code/,3.12 venv):
    python -m pytest tests/test_config_loader.py -v
"""
import dataclasses
import json

import pytest

from agent.config import (
    AgentConfig, build_agent_config, build_breaker_config, build_context_builder_params,
    build_guardrail_runner, build_memory_params, build_multiagent_params, build_provider_config,
    build_retry_policy, build_tool_executor_params, clear_cache, config_dir,
    default_provider, exit_words, get_section, load_guardrail_names, load_provider_config,
)
from agent.config import loader as loader_mod


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path, monkeypatch):
    """每次测试：AGENT_CONFIG_DIR 指向 tmp + 清缓存；结束恢复。"""
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(tmp_path))
    clear_cache()
    yield tmp_path
    clear_cache()


def _write(confdir, name: str, data: dict):
    """写一个 yaml(用 json.dumps,JSON 是 YAML 子集)并清缓存,让下一次读取生效。

    注意:这不模拟"改了文件但没 reload"——那由 test_clear_cache 用裸写专门测。
    """
    (confdir / f"{name}.yaml").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    clear_cache()


def _count_guards(runner) -> int:
    return sum(len(v) for v in runner._guards.values())


# ─────────────────── 缺 YAML = 纯默认 ───────────────────

def test_missing_config_dir_falls_back_to_pure_defaults(tmp_path):
    """空配置目录:build_agent_config() 逐字段等于 AgentConfig();default_provider 回落 "ark"。"""
    assert dataclasses.asdict(build_agent_config()) == dataclasses.asdict(AgentConfig())
    assert default_provider() == "ark"
    # provider 显式传名仍可用(api_key/base_url/model 走 env/.env)
    pc = build_provider_config("openai_compatible")
    assert pc.provider == "openai_compatible"


# ─────────────────── agent.yaml ───────────────────

def test_agent_config_yaml_overrides(tmp_path):
    """只覆盖 YAML 里的字段,其余吃 Python 默认。"""
    _write(tmp_path, "agent", {"temperature": 0.2, "max_steps": 7, "allowed_tools": ["bash"]})
    cfg = build_agent_config()
    assert cfg.temperature == 0.2
    assert cfg.max_steps == 7
    assert cfg.allowed_tools == ["bash"]
    assert cfg.model == AgentConfig().model          # 未写 -> 默认
    assert cfg.system_prompt == AgentConfig().system_prompt  # 永不走 YAML


def test_priority_python_default_lt_yaml(tmp_path):
    """yaml 设 step_timeout -> 生效(覆盖 Python 默认)。"""
    _write(tmp_path, "agent", {"step_timeout": 42.0})
    assert build_agent_config().step_timeout == 42.0


def test_exit_words(tmp_path):
    """agent.yaml exit_words;缺省 ["exit", "quit"]。"""
    assert exit_words() == ["exit", "quit"]
    _write(tmp_path, "agent", {"exit_words": ["quit", "q"]})
    assert exit_words() == ["quit", "q"]


# ─────────────────── provider.yaml ───────────────────

def test_provider_env_fallback(tmp_path, monkeypatch):
    """yaml base_url/model 为空 -> 回退读 env DEEPSEEK_MODEL。"""
    _write(tmp_path, "provider", {"providers": {"openai_compatible": {"model": "", "base_url": ""}}})
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    pc = build_provider_config("openai_compatible")
    assert pc.model == "env-model"


def test_provider_yaml_beats_env(tmp_path, monkeypatch):
    """yaml model 非空 -> 胜过 env DEEPSEEK_MODEL。"""
    _write(tmp_path, "provider", {"providers": {"openai_compatible": {"model": "yaml-model"}}})
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")
    assert build_provider_config("openai_compatible").model == "yaml-model"


def test_api_key_never_from_yaml(tmp_path, monkeypatch):
    """yaml 里塞 api_key -> 被忽略,只读 api_key_env 指定的 env。"""
    _write(tmp_path, "provider", {"providers": {"openai_compatible": {"api_key": "sk-in-yaml"}}})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    assert load_provider_config("openai_compatible").api_key == "sk-from-env"


def test_default_provider_priority(tmp_path, monkeypatch):
    """AGENT_PROVIDER env > provider.yaml default > "ark"。"""
    _write(tmp_path, "provider", {"default": "openai_compatible"})
    assert default_provider() == "openai_compatible"          # yaml default 生效
    monkeypatch.setenv("AGENT_PROVIDER", "ark")
    assert default_provider() == "ark"                        # env 胜过 yaml
    monkeypatch.delenv("AGENT_PROVIDER")
    _write(tmp_path, "provider", {})                          # 无 default -> 回落 "ark"
    assert default_provider() == "ark"


# ─────────────────── reliability.yaml ───────────────────

def test_retry_breaker_policies(tmp_path):
    """retry/breaker 缺省与 yaml 覆盖。"""
    assert (build_retry_policy().max_attempts, build_retry_policy().base_delay) == (3, 0.5)
    assert build_breaker_config().failure_threshold == 5
    _write(tmp_path, "reliability", {
        "retry": {"max_attempts": 5, "base_delay": 1.0},
        "breaker": {"failure_threshold": 9},
    })
    assert build_retry_policy().max_attempts == 5
    assert build_retry_policy().base_delay == 1.0
    assert build_breaker_config().failure_threshold == 9


def test_build_tool_executor_params(tmp_path):
    """execution 参数 + audit enabled/log_path/disabled。"""
    _write(tmp_path, "reliability", {
        "execution": {"retry_mode": "llm_retry", "parallel_semaphore": 4,
                      "max_workers": 2, "result_summary_chars": 120},
        "audit": {"enabled": True, "log_path": str(tmp_path / "audit.jsonl")},
    })
    p = build_tool_executor_params()
    assert p["retry_mode"] == "llm_retry"
    assert p["parallelism"] == 4
    assert p["max_workers"] == 2
    assert p["result_summary_chars"] == 120
    assert p["audit_logger"] is not None
    assert p["audit_logger"].log_path == str(tmp_path / "audit.jsonl")
    assert p["breaker_config"] is not None
    assert p["idempotency_store"] is not None

    # audit disabled -> audit_logger=None
    _write(tmp_path, "reliability", {"audit": {"enabled": False}})
    assert build_tool_executor_params()["audit_logger"] is None


# ─────────────────── context / memory / multiagent ───────────────────

def test_build_context_builder_params(tmp_path):
    """context.yaml builder 段:缺省 + 覆盖(不含 context_budget)。
    keep_recent/gap_threshold_minutes 对齐 CC(keepRecent=5 / gapThresholdMinutes=60)。"""
    assert build_context_builder_params() == {
        "tool_result_threshold": 2000, "keep_recent": 5,
        "keep_recent_turns": 4, "memory_recall_top_k": 3,
        "gap_threshold_minutes": 60,
    }
    _write(tmp_path, "context", {"builder": {
        "tool_result_threshold": 5000, "keep_recent": 2,
        "keep_recent_turns": 6, "memory_recall_top_k": 5,
    }})
    assert build_context_builder_params() == {
        "tool_result_threshold": 5000, "keep_recent": 2,
        "keep_recent_turns": 6, "memory_recall_top_k": 5,
        "gap_threshold_minutes": 60,
    }


def test_build_memory_params(tmp_path):
    assert build_memory_params() == {"recall_top_k": 5, "index_file": "MEMORY.md"}
    _write(tmp_path, "memory", {"recall_top_k": 2, "index_file": "INDEX.md"})
    assert build_memory_params() == {"recall_top_k": 2, "index_file": "INDEX.md"}


def test_build_multiagent_params(tmp_path):
    assert build_multiagent_params() == {"max_handoffs": 5}
    _write(tmp_path, "multiagent", {"orchestrator": {"max_handoffs": 8}})
    assert build_multiagent_params() == {"max_handoffs": 8}


# ─────────────────── guardrails.yaml ───────────────────

def test_guardrail_names_default_and_factory(tmp_path):
    """缺省 4 个 guard(阶段0 起权限三 guard 移到 can_use_tool);
    build_guardrail_runner 装配成功;未知名 raise。"""
    assert load_guardrail_names() == [
        "prompt_injection", "pii", "indirect_injection", "pii_tool_result",
    ]
    assert _count_guards(build_guardrail_runner()) == 4
    _write(tmp_path, "guardrails", {"enabled": ["prompt_injection", "pii"]})
    assert _count_guards(build_guardrail_runner()) == 2
    _write(tmp_path, "guardrails", {"enabled": ["bogus_guard"]})
    with pytest.raises(ValueError):
        build_guardrail_runner()


# ─────────────────── loader 机制 ───────────────────

def test_clear_cache(tmp_path):
    """改 yaml 后须 clear_cache() 才重新加载。"""
    _write(tmp_path, "agent", {"temperature": 0.2})
    assert build_agent_config().temperature == 0.2
    # 裸写绕过 _write 的自动 clear,模拟"改了文件但没 reload"
    (tmp_path / "agent.yaml").write_text(
        json.dumps({"temperature": 0.9}, ensure_ascii=False), encoding="utf-8")
    assert build_agent_config().temperature == 0.2      # 缓存未清
    clear_cache()
    assert build_agent_config().temperature == 0.9      # 清后重新读


def test_config_dir_resolution(tmp_path, monkeypatch):
    """AGENT_CONFIG_DIR 生效;未设时回落 code/config/。"""
    assert config_dir() == tmp_path
    monkeypatch.delenv("AGENT_CONFIG_DIR")
    assert config_dir() == loader_mod._BASE / "config"


def test_import_no_side_effect():
    """import 不读文件、不触发 env 覆盖;首次 get_section 才填充缓存。"""
    clear_cache()
    assert loader_mod._CACHE is None
    get_section("agent")
    assert loader_mod._CACHE is not None
