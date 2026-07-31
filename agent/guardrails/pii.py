# guardrails/pii.py - 输出层:PII 脱敏 + 工具结果诱导检测(阶段8 任务5,题12/13/18)
# 对比 CC:CC 无 PII 脱敏(靠模型本身);我们做正则脱敏。
import re

from .guardrail import Guardrail, GuardrailResult

# PII 模式:手机号 / 身份证 / 邮箱
_PHONE = re.compile(r"1[3-9]\d{9}")
_IDCARD = re.compile(r"\d{17}[\dXx]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 工具结果中的 prompt 注入(防 indirect injection)
_INJECTION_IN_RESULT = re.compile(r"忽略(以上|之前|前面)(的)?(指令|规则)")


def _mask_phone(m: re.Match) -> str:
    s = m.group(0)
    return s[:3] + "****" + s[-4:]


def _mask_idcard(m: re.Match) -> str:
    s = m.group(0)
    return s[:6] + "********" + s[-4:]


class PIIGuard(Guardrail):
    """on_output:正则检测 PII(手机号/身份证/邮箱)并脱敏。"""
    mount = "on_output"
    name = "pii"

    def check(self, payload, context) -> GuardrailResult:
        text = payload if isinstance(payload, str) else str(payload)
        sanitized = _PHONE.sub(_mask_phone, text)
        sanitized = _IDCARD.sub(_mask_idcard, sanitized)
        sanitized = _EMAIL.sub("[邮箱已脱敏]", sanitized)
        if sanitized != text:
            return GuardrailResult(passed=True, reason="PII 脱敏",
                                   action="sanitize", sanitized=sanitized)
        return GuardrailResult(passed=True, action="allow")


class IndirectInjectionGuard(Guardrail):
    """after_tool:工具结果含 prompt 注入(忽略指令等)-> 拦截,防模型被工具结果诱导。"""
    mount = "after_tool"
    name = "indirect_injection"

    def check(self, payload, context) -> GuardrailResult:
        result = payload
        text = getattr(result, "text", "") or ""
        if _INJECTION_IN_RESULT.search(text):
            return GuardrailResult(
                passed=False,
                reason="工具结果含疑似 prompt 注入,已拦截(防 indirect injection)",
                action="block",
            )
        return GuardrailResult(passed=True, action="allow")
