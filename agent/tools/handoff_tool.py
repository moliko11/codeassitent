# handoff 工具(阶段10 commit 8,题13/14)
# 模型(orchestrator)调本工具把任务整体交给另一 agent。区别 tool_call 调函数拿结果:
# handoff = "把任务整体交给另一 agent 跑",orchestrator 检测到本工具返回后 delegate 给目标 worker。
#
# handler 返回结构化 dict(to_role/context);formatter 包成 JSON 工具结果:
#   {"ok": true, "tool": "handoff", "data": {"to_role": ..., "context": ...}}
# orchestrator 的 detect_handoff(multiagent/handoff.py)解析 tool 消息里的该 JSON。
#
# 注册方式:工厂 make_handoff_tool()(对齐 make_save_memory_tool),由 OrchestratorAgent
# 按需注册进自己的 registry(不全局注册,避免污染单 agent 的工具列表/破坏现有测试)。
from .defs import Tool, ToolSpec

HANDOFF_SCHEMA = {
    "type": "object",
    "properties": {
        "to_role": {"type": "string", "description": "目标 agent 角色名(如 search/coder/reviewer)"},
        "context": {"type": "string", "description": "交给目标 agent 的子任务/上下文描述"},
    },
    "required": ["to_role", "context"],
}


def make_handoff_tool() -> Tool:
    """造 handoff 工具。无闭包状态(纯返回 dict),工厂形式仅为按需注册、对齐 make_save_memory_tool。"""
    def handler(to_role: str, context: str):
        return {"to_role": to_role, "context": context}
    return Tool(
        tool_spec=ToolSpec(
            name="handoff",
            description=(
                "把当前任务整体交给另一个 agent(角色)执行。orchestrator 用来委派子任务给专职 worker。"
                "to_role=目标 agent 角色;context=子任务描述。调用后 orchestrator 会把任务交给该 agent。"
            ),
            input_schema=HANDOFF_SCHEMA,
        ),
        handler=handler,
    )
