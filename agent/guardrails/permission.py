# guardrails/permission.py - 工具层:权限白名单 + 高风险审批(阶段8 任务3,题5/6/7/8/14/15)
# 对比 CC:CC 用 canUseTool + PermissionMode(read-only/plan/default/acceptEdits);
# 我们做 allowed_tools 白名单 + high_risk 标记触发 HITL。
from .guardrail import Guardrail, GuardrailResult


class PermissionGuard(Guardrail):
    """before_tool:工具不在 allowed_tools 白名单则拦截。空白名单=全允许(默认)。"""
    mount = "before_tool"
    name = "permission"

    def check(self, payload, context) -> GuardrailResult:
        call = payload
        allowed = getattr(getattr(context, "config", None), "allowed_tools", []) or []
        if allowed and call.tool_name not in allowed:
            return GuardrailResult(
                passed=False,
                reason=f"工具 {call.tool_name} 不在允许列表(allowed_tools)",
                action="block",
            )
        return GuardrailResult(passed=True, action="allow")


class HighRiskGuard(Guardrail):
    """before_tool:高风险工具(ToolSpec.high_risk=True)触发 HITL(needs_approval)。"""
    mount = "before_tool"
    name = "high_risk"

    def check(self, payload, context) -> GuardrailResult:
        call = payload
        registry = getattr(context, "registry", None)
        if registry is None:
            return GuardrailResult(passed=True, action="allow")
        try:
            tool = registry.get_tool(call.tool_name)
            if getattr(tool.tool_spec, "high_risk", False):
                return GuardrailResult(
                    passed=False,
                    reason=f"高风险工具 {call.tool_name} 需人工审批",
                    action="needs_approval",
                )
        except Exception:
            pass  # 工具不存在交 precheck 处理,不在此拦截
        return GuardrailResult(passed=True, action="allow")
