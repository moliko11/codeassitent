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


def _mask_pii(text: str) -> str:
    """对文本做 PII 脱敏(手机/身份证/邮箱),返回脱敏后文本。"""
    sanitized = _PHONE.sub(_mask_phone, text)
    sanitized = _IDCARD.sub(_mask_idcard, sanitized)
    sanitized = _EMAIL.sub("[邮箱已脱敏]", sanitized)
    return sanitized


def _mask_pii_obj(obj):
    """递归对 obj 中的字符串值脱敏(dict/list/tuple/str),返回同结构副本。
    供 ToolResultPIIGuard 清 result.data 中的 PII(data 可能是 str/dict/list)。"""
    if isinstance(obj, str):
        return _mask_pii(obj)
    if isinstance(obj, dict):
        return {k: _mask_pii_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_pii_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_mask_pii_obj(v) for v in obj)
    return obj


class PIIGuard(Guardrail):
    """on_output:正则检测 PII(手机号/身份证/邮箱)并脱敏。"""
    mount = "on_output"
    name = "pii"

    def check(self, payload, context) -> GuardrailResult:
        text = payload if isinstance(payload, str) else str(payload)
        sanitized = _mask_pii(text)
        if sanitized != text:
            return GuardrailResult(passed=True, reason="PII 脱敏",
                                   action="sanitize", sanitized=sanitized)
        return GuardrailResult(passed=True, action="allow")


class ToolResultPIIGuard(Guardrail):
    """after_tool:工具结果中的 PII 脱敏(result.text + result.data 的字符串值)。

    on_output 的 PIIGuard 只管最终回复文本;工具结果(web/read/bash 抓回的内容)里的 PII 会原样
    进 transcript/trace/audit。本 guard 在 after_tool 清 text + data,堵住工具结果侧 PII 落盘(对齐 #12)。
    原地改 result.text/data,返回 sanitize + sanitized=result,registry 用它替换 result。
    """
    mount = "after_tool"
    name = "pii_tool_result"

    def check(self, payload, context) -> GuardrailResult:
        result = payload
        text = getattr(result, "text", None)
        data = getattr(result, "data", None)
        new_text = _mask_pii(text) if isinstance(text, str) else text
        new_data = _mask_pii_obj(data)
        if new_text == text and new_data == data:
            return GuardrailResult(passed=True, action="allow")
        result.text = new_text
        result.data = new_data
        return GuardrailResult(passed=True, reason="工具结果 PII 脱敏",
                               action="sanitize", sanitized=result)


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
