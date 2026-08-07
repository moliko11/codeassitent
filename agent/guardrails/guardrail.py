# guardrails/guardrail.py - 安全护栏接口与运行器(阶段8 任务1,题19/20)
# 四挂载点:on_input(用户输入前)/before_tool(执行前)/after_tool(结果后)/on_output(最终回答前)
# 对比 CC:CC 无 Guardrail 框架(靠 canUseTool + 路径校验 + prompt);我们做显式四挂载点为学范式。
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

MountPoint = Literal["on_input", "before_tool", "after_tool", "on_output"]


@dataclass
class GuardrailResult:
    """Guardrail.check 的返回。

    - passed=True + action=allow:通过
    - passed=False + action=block:拦截(不执行/不回填)
    - action=sanitize:passed=True 但内容需脱敏(sanitized 放脱敏后内容)

    阶段0(Phase A):needs_approval 已删——HITL 提到 async can_use_tool(executor 层,
    工具执行前,走 confirmer),不再由同步 guardrail 产 HITL 信号。见 hitl-approval-design.md §3。
    """
    passed: bool
    reason: str = ""
    action: Literal["allow", "block", "sanitize"] = "allow"
    sanitized: Any = None  # action=sanitize 时放脱敏后的内容


class Guardrail(ABC):
    """安全护栏基类。mount 决定挂载点;子类实现 check。

    payload 类型按挂载点不同:
    - on_input: str(user_input)
    - before_tool: ToolCall
    - after_tool: ToolResult
    - on_output: str(final_response.text)
    """
    mount: MountPoint
    name: str

    @abstractmethod
    def check(self, payload: Any, context: Any) -> GuardrailResult:
        """检查 payload,返回 GuardrailResult。"""


class GuardrailRunner:
    """按挂载点跑所有注册的 Guardrail。

    规则:
    - block 即短路(返回该结果,不跑后续)
    - sanitize 累积(多个 sanitize 叠加,后一个拿前一个的 sanitized 作输入)
    - allow 不影响,继续下一个
    - 全通过:有 sanitize 发生则返回 sanitize(带最终 sanitized),否则 allow
    """

    def __init__(self):
        self._guards: dict[str, list[Guardrail]] = {
            "on_input": [], "before_tool": [], "after_tool": [], "on_output": [],
        }

    def register(self, guard: Guardrail) -> "GuardrailRunner":
        self._guards[guard.mount].append(guard)
        return self

    def run(self, mount: MountPoint, payload: Any, context: Any) -> GuardrailResult:
        """跑指定挂载点的所有 Guardrail。返回最终结果。"""
        current = payload
        sanitized_happened = False
        for g in self._guards.get(mount, []):
            result = g.check(current, context)
            if result.action == "block":
                return result  # 短路
            if result.action == "sanitize" and result.sanitized is not None:
                current = result.sanitized
                sanitized_happened = True
            # allow:继续
        if sanitized_happened:
            return GuardrailResult(passed=True, reason="sanitized",
                                   action="sanitize", sanitized=current)
        return GuardrailResult(passed=True, action="allow")
