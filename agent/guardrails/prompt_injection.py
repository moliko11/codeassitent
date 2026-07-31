# guardrails/prompt_injection.py - 输入层:Prompt 注入启发式检测(阶段8 任务2,题1/2/3/4/17)
# 对比 CC:CC 无独立组件(纯 prompt 防护);我们做启发式正则+关键词。
import re

from .guardrail import Guardrail, GuardrailResult

# 启发式模式:忽略指令 / 角色劫持 / 指令与内容混合
_INJECTION_PATTERNS = [
    re.compile(r"忽略(以上|之前|前面|上述)(的)?(所有)?(指令|规则|提示)"),
    re.compile(r"ignore (all )?(previous|above|prior) instructions", re.IGNORECASE),
    re.compile(r"你现在是(一个)?(无限制的|不受限的|自由的)"),
    re.compile(r"you are now (a )?(unrestricted|free|unfiltered)", re.IGNORECASE),
    re.compile(r"(不要|别)(遵守|遵循)(任何|的)?(规则|限制|约束)"),
    re.compile(r"system prompt[:：].*忽略", re.IGNORECASE),
]


class PromptInjectionGuard(Guardrail):
    """on_input:检测用户输入的 prompt 注入。启发式正则,不用 LLM(成本高/不稳)。"""
    mount = "on_input"
    name = "prompt_injection"

    def check(self, payload, context) -> GuardrailResult:
        text = payload if isinstance(payload, str) else str(payload)
        for pat in _INJECTION_PATTERNS:
            if pat.search(text):
                return GuardrailResult(
                    passed=False,
                    reason=f"疑似 prompt 注入(命中模式:{pat.pattern[:30]})",
                    action="block",
                )
        return GuardrailResult(passed=True, action="allow")
