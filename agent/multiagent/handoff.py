# multiagent/handoff.py - Handoff action(阶段10,题13/14)
# handoff = 把任务整体交给另一个 agent(区别 tool_call 调函数拿结果)。
# 实现为特殊 tool(commit 8 的 handoff_tool):模型调 handoff 工具,handler 返回标记字符串,
# orchestrator 跑完一轮用 detect_handoff 解析标记 -> Handoff,再 delegate 给目标 worker。
# 对标 CC:CC 用 subagent 工具(不是显式 handoff action);我们简化为 tool + 标记解析(§8.5)。
import re
from dataclasses import dataclass
from typing import Optional

from ..core.state import AgentState


@dataclass
class Handoff:
    """一次 handoff:把当前任务整体交给 to_role 的 agent,带上 context 子任务描述。"""
    to_role: str       # 目标 agent role(orchestrator.workers 的 key)
    context: str       # 传递给目标 agent 的子任务/上下文


# handoff 工具(commit 8)返回标记格式:[handoff] {to_role}\n{context}
# 用正则解析;to_role 取标记后第一个空白分隔的 token,context 取其余(可多行)。
_HANDOFF_RE = re.compile(r"\[handoff\]\s*(\S+)[ \t]*\r?\n?(.*)", re.DOTALL)


def detect_handoff(state: AgentState) -> Optional[Handoff]:
    """扫描 state.messages 的 tool 消息,找 [handoff] 标记,返回最后一条(最近一次 handoff 意图)。

    orchestrator 每轮 super().run() 产出的 tool 结果里若含 handoff 工具的返回标记,
    即模型要求 handoff;无标记 -> 模型选择 FINISH,orchestrator 结束。
    取最后一条:一轮内模型可能多次调 handoff(理论),以最后一次为准。
    """
    last: Optional[Handoff] = None
    for m in getattr(state, "messages", []):
        if getattr(m, "role", None) != "tool":
            continue
        text = m.content if isinstance(m.content, str) else str(m.content)
        mo = _HANDOFF_RE.search(text)
        if mo:
            last = Handoff(to_role=mo.group(1).strip(), context=mo.group(2).strip())
    return last
