# persist/replay.py
import logging

from ..core.state import AgentState, AgentStep, ToolHistoryEntry
from ..core.models import ModelResponse
from ..core.messages import Message
from ..tools.defs import ToolCall, ToolResult
from ..adapters.base import BaseModelAdapter
from .store import read_transcript

_log = logging.getLogger(__name__)


def apply_message(state: AgentState, rec: dict, adapter: BaseModelAdapter):
    """逐条消息重放，重建 messages/steps/派生状态。幂等：同序重放得同 state。
    schema 容错（硬伤 4）：单条损坏/缺字段 try/except 跳过+告警，resume 是最后防线，不整体崩。"""
    try:
        t = rec["type"]
        if t == "user":
            state.messages.append(Message(role="user", content=rec["content"]))

        elif t == "assistant":
            step = state.new_step()                       # 每条 assistant = 新 step
            mr = ModelResponse(
                text=rec["text"],
                tool_calls=[ToolCall(**c) for c in rec["tool_calls"]],
            )
            step.model_response = mr
            # 解耦（硬伤 3）：assistant 单独 append。有 tool_calls / 无 tool_calls（final）都进 messages
            # 作历史（推翻 Decision 3：多轮对话需要上一轮 final 作上下文）。
            # final（无 tool_calls）不设终态：多轮 session 中间轮 final 不是 session 终态，
            # 终态统一由 run_end 记录决定（崩场景无 run_end -> 非终态可续跑）。
            state.messages = adapter.append_assistant(state.messages, mr)
            if not mr.tool_calls:
                state.final_response = mr

        elif t == "tool_result":                          # 逐 result 增量记录（硬伤 1，非批量）
            r = ToolResult(**rec["result"])
            state.messages = adapter.append_tool_result(state.messages, r)
            state.steps[-1].tool_results.append(r)
            state.tool_history.append(ToolHistoryEntry(   # 派生：tool_history 重算
                call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
                error_type=(r.error or {}).get("type")))

        elif t == "run_end":
            state.status = rec["status"]
        # 其余类型 default 跳过（前向兼容）
    except Exception as e:
        _log.warning("apply_message 跳过损坏/不合 schema 的记录: %s", e)


def _detect_pending(state: AgentState):
    """末条 assistant 的 tool_calls 中，无对应 tool_result 记录的子集 = pending（per-call_id）。"""
    if not state.steps:
        return
    last_mr = state.steps[-1].model_response
    if not last_mr or not last_mr.tool_calls:
        return
    done = {r.call_id for r in state.steps[-1].tool_results}
    state.pending_tool_calls = [c for c in last_mr.tool_calls if c.call_id not in done]


def resume(run_id: str, config, adapter: BaseModelAdapter) -> AgentState:
    """恢复 = load transcript + 全重放（CC 同款，无周期快照）。system 从 config 重建，不落盘。"""
    state = AgentState(run_id=run_id, max_steps=config.max_steps)
    state.messages = ([Message(role="system", content=config.system_prompt)]
                      if config.system_prompt else [])
    for rec in read_transcript(run_id):          # 跳过损坏行
        apply_message(state, rec, adapter)
    _detect_pending(state)                        # 崩在工具执行中 -> 标 pending（per-call_id）
    return state


def replay(run_id: str, config, adapter: BaseModelAdapter) -> AgentState:
    """重放看过程，不调 LLM、不重执行工具：用录好的 assistant/tool_result（逐条）。
    与 resume 的重放完全一样，区别仅在调用方是否续跑。"""
    state = AgentState(run_id=run_id, max_steps=config.max_steps)
    state.messages = ([Message(role="system", content=config.system_prompt)]
                      if config.system_prompt else [])
    for rec in read_transcript(run_id):
        apply_message(state, rec, adapter)
    return state                                  # step 序列与原 run 一致；全程 0 次 LLM 调用