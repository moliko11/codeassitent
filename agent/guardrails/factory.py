# agent/guardrails/factory.py —— guard 名→类映射 + 装配护栏链(阶段8,由 guardrails.yaml 控制启用清单)
#
# guardrails.yaml 只外置"启用哪些 guard"；规则内容(PII 正则/prompt_injection 模式/git 白名单)留在代码。
# 未知名 raise(fail-fast):拼错 guard 名直接报错,防静默丢护栏。
from .guardrail import GuardrailRunner
from .prompt_injection import PromptInjectionGuard
from .permission import PermissionGuard, HighRiskGuard
from .git_safety import GitSafetyGuard
from .pii import PIIGuard, IndirectInjectionGuard, ToolResultPIIGuard

# key 必须与 config/guardrails.yaml 的 enabled 完全一致。
_GUARDS = {
    "prompt_injection": PromptInjectionGuard,
    "permission": PermissionGuard,
    "high_risk": HighRiskGuard,
    "git_safety": GitSafetyGuard,
    "pii": PIIGuard,
    "indirect_injection": IndirectInjectionGuard,
    "pii_tool_result": ToolResultPIIGuard,
}


def build_guardrail_runner(names: list[str] | None = None) -> GuardrailRunner:
    """按 guard 名清单装配 GuardrailRunner。names=None 时从 guardrails.yaml 读(缺省 7 个)。"""
    from ..config.loader import load_guardrail_names
    names = names if names is not None else load_guardrail_names()
    runner = GuardrailRunner()
    for n in names:
        cls = _GUARDS.get(n)
        if cls is None:
            raise ValueError(f"未知 guard: {n}，可选: {sorted(_GUARDS)}")
        runner.register(cls())
    return runner
