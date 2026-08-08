# multiagent/handoff.py - Handoff action(阶段10,题13/14)
# handoff = 把任务整体交给另一个 agent(区别 tool_call 调函数拿结果)。
# 实现为 tool(commit 8 的 handoff_tool):模型调 handoff 工具,handler 返回 {to_role, context},
# formatter 包成 JSON 工具结果;orchestrator 跑完一轮用 detect_handoff 解析 -> Handoff,再 delegate。
# 对标 CC:CC 用 subagent 工具(不是显式 handoff action);我们简化为 tool + 结果解析(§8.5)。
import json
from dataclasses import dataclass
from typing import Any, Optional

from ..core.state import AgentState


@dataclass
class Handoff:
    """一次 handoff:把当前任务整体交给 to_role 的 agent,带上 context 子任务描述。"""
    to_role: str       # 目标 agent role(orchestrator.workers 的 key)
    context: str       # 传递给目标 agent 的子任务/上下文


def _tool_result_text(content: Any) -> Optional[str]:
    """从 message.content 提取工具结果文本。

    结构化后(content 恒为文本)直接返回;非 str(多模态/防御)返回 None。
    修泄漏:不再兼容 mock/openai_compat/ark 三种 dict 格式——适配器统一产出文本 content。
    """
    return content if isinstance(content, str) else None


def detect_handoff(state: AgentState) -> Optional[Handoff]:
    """扫描 state.messages,找 handoff 工具的结果(取最后一条),返回 Handoff;无 -> None。

    handoff 工具结果经 formatter 为 JSON:{"ok": true, "tool": "handoff", "data": {to_role, context}}。
    逐消息提取工具结果文本 -> JSON 解析 -> tool=="handoff" 取 data。非 JSON / 非 handoff 跳过。
    无 handoff 结果 = 模型选择 FINISH,orchestrator 结束。
    """
    last: Optional[Handoff] = None
    for m in getattr(state, "messages", []):
        text = _tool_result_text(getattr(m, "content", None))
        if not text:
            continue
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict) or obj.get("tool") != "handoff":
            continue
        data = obj.get("data") or {}
        to_role = data.get("to_role")
        if to_role:
            last = Handoff(to_role=str(to_role), context=str(data.get("context", "")))
    return last
