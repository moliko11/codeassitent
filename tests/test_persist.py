"""阶段 5 验收测试：Checkpoint / 中断恢复（消息级，CC 同款）。

覆盖 checkpoint-impl.md §6 三项验收：
- ① kill 后 resume 不重复工具调用（已完成的用录好的 result，续跑只跑新的）
- ② replay 不调 LLM（全程 0 次 stream_llm/call_llm）
- ③ 崩在工具执行中，per-call_id 只重跑无 result 记录的 call_id

不依赖真实 LLM API。运行（从 code/ 目录，3.12 venv）：
    python -m pytest tests/test_persist.py -v
"""
import pytest

from agent.agentloop import agentloop, continue_loop, _run_turn, _emit_run_end
from agent.persist import resume, replay, Persister, read_transcript
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.core.models import ModelResponse
from agent.tools.defs import Tool, ToolCall, ToolResult, ToolSpec
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.adapters.base import BaseModelAdapter
from agent.core.messages import Message
from agent.streaming.sink import NullSink


# ───────────────────────── 测试夹具与 helpers ─────────────────────────

@pytest.fixture(autouse=True)
def _tmp_persist_root(tmp_path, monkeypatch):
    """把 PERSIST_ROOT 指到 tmp_path，测试落盘不污染 code/persist。

    run_dir 读模块级 PERSIST_ROOT（运行时查找），monkeypatch 改它即生效，
    Persister / read_transcript 都跟着走 tmp。
    """
    from agent.persist import paths
    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")


class _ScriptedAdapter(BaseModelAdapter):
    """按脚本顺序返回 ModelResponse 的假适配器，并计数 call_llm 调用次数。

    resume / replay 只会调 append_assistant / append_tool_result（不调 call_llm）；
    continue_loop 续跑才调 call_llm。用 call_count 区分“是否重调了 LLM”。
    append_* 返回原 messages（测试不关心 provider 回填格式，断言靠 steps /
    tool_history / pending / 工具 handler 计数）。
    """

    def __init__(self, script: list[ModelResponse]):
        super().__init__(api_key="", base_url="", model="")
        self.script = script
        self.i = 0
        self.call_count = 0

    def call_llm(self, request):
        self.call_count += 1
        resp = self.script[self.i]
        self.i += 1
        return resp

    def append_assistant(self, messages, model_response):
        # 模拟真实 provider：copy + append（返回新 list），让多轮 messages 累积可测（bug1/bug2）
        new_messages = list(messages)
        new_messages.append(Message(role="assistant", content=model_response.text or ""))
        return new_messages

    def append_tool_result(self, messages, result):
        new_messages = list(messages)
        new_messages.append(Message(role="tool", content=result.text or ""))
        return new_messages


def _echo_registry():
    """注册一个 echo 工具，handler 记录每次调用的参数，用于断言“哪个工具被重跑”。"""
    reg = ToolRegistry()
    calls: list[dict] = []

    def handler(**kwargs):
        calls.append(dict(kwargs))
        return {"echoed": kwargs}

    reg.register(Tool(
        tool_spec=ToolSpec(
            name="echo",
            description="echo back arguments",
            input_schema={"type": "object"},  # 宽松 schema，任意 arguments 都过
        ),
        handler=handler,
    ))
    return reg, calls


def _seed(run_id: str, ops: list[tuple]):
    """用 Persister 落盘一组消息，模拟 live run 的 transcript 产物。

    ops: [(method_name, arg), ...]，method ∈ log_user/log_assistant/
    log_tool_result/log_run_end。用 Persister API 落盘保证格式与 live 一致
    （apply_message 能正确重放）。
    """
    p = Persister(run_id)
    for method, arg in ops:
        getattr(p, method)(arg)
    p.close()


def _ctx(reg, adapter, state=None, persist=True):
    return RuntimeContext(
        registry=reg,
        tool_executor=ToolExecutor(reg),
        model_adapter=adapter,
        config=AgentConfig(max_steps=10, system_prompt=""),
        state=state or AgentState(),
        sink=NullSink(),
        persist=persist,
    )


# ───────────────────────── 验收 ②：replay 不调 LLM ─────────────────────────

def test_replay_no_llm_call():
    """验收 ②：跑一次 live 落盘 -> replay 用新 adapter -> 全程 0 次 call_llm，
    且重建的 state 与原 run 一致（steps / tool_history / status）。"""
    # 1. 跑一次 live（persist=True 落盘）：1 轮工具 + 1 轮 final
    reg, tool_calls = _echo_registry()
    live_adapter = _ScriptedAdapter([
        ModelResponse(tool_calls=[ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})]),
        ModelResponse(text="done"),
    ])
    live_state = agentloop("hi", _ctx(reg, live_adapter))
    run_id = live_state.run_id

    assert live_state.status == "completed"
    assert len(live_state.steps) == 2          # 1 工具轮 + 1 final
    assert len(live_state.tool_history) == 1
    assert live_adapter.call_count == 2        # live 调了 2 次 LLM

    # 2. replay：全新 adapter，不调 LLM
    replay_adapter = _ScriptedAdapter([ModelResponse(text="should-not-be-used")])
    state = replay(run_id, AgentConfig(max_steps=10, system_prompt=""), replay_adapter)

    # 3. 断言：全程 0 次 LLM，state 与原 run 一致
    assert replay_adapter.call_count == 0
    assert state.status == "completed"
    assert len(state.steps) == len(live_state.steps)
    assert len(state.tool_history) == len(live_state.tool_history)
    assert state.tool_history[0].call_id == "c1"


# ───────────────────────── 验收 ①：resume 不重复工具调用 ─────────────────────────

def test_resume_no_replay_of_done_tools():
    """验收 ①：构造“跑了 2 步工具轮、无 final/run_end”的 transcript（模拟 kill 在中途）
    -> resume 重建（不调 LLM、不重跑工具）-> continue_loop 续跑只跑新工具。"""
    run_id = "t-resume-done"
    # 模拟 live 跑了 2 步工具轮后崩在“第 3 步 LLM 前”：有 c1/c2 的 assistant+result，无 final
    _seed(run_id, [
        ("log_user", "hi"),
        ("log_assistant", ModelResponse(tool_calls=[
            ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})])),
        ("log_tool_result", ToolResult(call_id="c1", tool_name="echo", ok=True, data={})),
        ("log_assistant", ModelResponse(tool_calls=[
            ToolCall(call_id="c2", tool_name="echo", arguments={"x": 2})])),
        ("log_tool_result", ToolResult(call_id="c2", tool_name="echo", ok=True, data={})),
    ])

    reg, tool_calls = _echo_registry()
    # 续跑脚本：第 1 轮返回新工具 c3，第 2 轮返回 final
    adapter = _ScriptedAdapter([
        ModelResponse(tool_calls=[ToolCall(call_id="c3", tool_name="echo", arguments={"x": 3})]),
        ModelResponse(text="done"),
    ])
    config = AgentConfig(max_steps=10, system_prompt="")

    # resume：全重放，不调 LLM、不重跑工具
    state = resume(run_id, config, adapter)
    assert adapter.call_count == 0               # resume 不调 LLM
    assert len(state.steps) == 2                 # 重建出 2 步
    assert len(state.tool_history) == 2
    assert state.pending_tool_calls == []        # c1/c2 都有 result，无 pending
    assert tool_calls == []                       # resume 没重跑任何工具

    # continue_loop 续跑
    state2 = continue_loop(state, _ctx(reg, adapter, state=state))

    # 断言：只跑了续跑的新工具 c3，c1/c2 未被重调
    assert len(tool_calls) == 1
    assert tool_calls[0] == {"x": 3}
    assert adapter.call_count == 2               # 续跑调了 2 次 LLM（c3 轮 + done 轮）
    assert state2.status == "completed"
    assert len(state2.steps) == 4                # 2 录制 + c3 + done


# ───────────────────────── 验收 ③：崩在工具执行中，per-call_id ─────────────────────────

def test_resume_pending_per_call_id():
    """验收 ③：构造半成品 transcript——assistant 请求 c1/c2，只落了 c1 的 result
    （崩在 c2 执行中）-> resume 标 pending=[c2] -> continue_loop 只重跑 c2，c1 不重跑。"""
    run_id = "t-pending"
    _seed(run_id, [
        ("log_user", "hi"),
        ("log_assistant", ModelResponse(tool_calls=[
            ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1}),
            ToolCall(call_id="c2", tool_name="echo", arguments={"x": 2}),
        ])),
        ("log_tool_result", ToolResult(call_id="c1", tool_name="echo", ok=True, data={})),
        # c2 无 result —— 模拟崩在 c2 执行中
    ])

    reg, tool_calls = _echo_registry()
    adapter = _ScriptedAdapter([ModelResponse(text="done")])  # 续跑直接 final
    config = AgentConfig(max_steps=10, system_prompt="")

    state = resume(run_id, config, adapter)
    # per-call_id：只 c2 无 result 记录 -> pending=[c2]，c1 有 result 不进 pending
    assert [c.call_id for c in state.pending_tool_calls] == ["c2"]
    assert adapter.call_count == 0
    assert tool_calls == []                       # resume 没执行任何工具

    state2 = continue_loop(state, _ctx(reg, adapter, state=state))

    # 断言：c2 被重跑（无 result 记录），c1 未被重跑（有录好的 result 充当幂等表）
    assert len(tool_calls) == 1
    assert tool_calls[0] == {"x": 2}
    assert state2.status == "completed"


# ───────────────────────── 额外健壮性（impl §6）─────────────────────────

def test_resume_idempotent():
    """同 run 重复 resume -> state 一致（幂等）。apply_message 不依赖墙钟/外部态。"""
    run_id = "t-idempotent"
    _seed(run_id, [
        ("log_user", "hi"),
        ("log_assistant", ModelResponse(tool_calls=[
            ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})])),
        ("log_tool_result", ToolResult(call_id="c1", tool_name="echo", ok=True, data={})),
        ("log_assistant", ModelResponse(text="done")),
        ("log_run_end", "completed"),
    ])
    config = AgentConfig(max_steps=10, system_prompt="")
    s1 = resume(run_id, config, _ScriptedAdapter([]))
    s2 = resume(run_id, config, _ScriptedAdapter([]))
    assert s1.status == s2.status == "completed"
    assert len(s1.steps) == len(s2.steps)
    assert [h.call_id for h in s1.tool_history] == [h.call_id for h in s2.tool_history]


def test_resume_skips_corrupt_line():
    """transcript 末尾有损坏行 -> resume 跳过损坏行正常恢复（容错，硬伤 4.2）。"""
    run_id = "t-corrupt"
    # 先正常落盘
    _seed(run_id, [
        ("log_user", "hi"),
        ("log_assistant", ModelResponse(text="done")),
        ("log_run_end", "completed"),
    ])
    # 追加一行损坏 JSON
    from agent.persist.paths import transcript_path
    with open(transcript_path(run_id), "a", encoding="utf-8") as f:
        f.write("{这不是合法 json\n")
    state = resume(run_id, AgentConfig(max_steps=10, system_prompt=""), _ScriptedAdapter([]))
    assert state.status == "completed"           # 损坏行被跳过，正常恢复


# ───────────────────────── 多轮 REPL 会话级持久化（方案A，对齐 CC）─────────────────────────

def test_repl_session_single_transcript():
    """多轮 REPL 共用一个 run_id -> 同一个 transcript.jsonl，整个 session 只有 1 个 run_end，
    跨轮 messages 累积。模拟 run_agent_loop 的 session 级循环（_run_turn + 共用 persister）。"""
    reg, _ = _echo_registry()
    adapter = _ScriptedAdapter([
        ModelResponse(text="reply-1"),
        ModelResponse(text="reply-2"),
    ])
    run_id = "t-repl-session"
    p = Persister(run_id)
    messages: list = []

    # 轮 1
    s1 = AgentState(run_id=run_id, max_steps=10)
    s1.messages = messages
    ctx1 = _ctx(reg, adapter, state=s1)
    s1 = _run_turn("msg-1", s1, ctx1, p)
    _emit_run_end(s1, ctx1.sink)          # 每轮只发 UI 事件，不 log_run_end
    messages = s1.messages                 # REPL 同步（bug2：append 返回 copy，需同步回 messages）
    # 轮 2（共用 run_id + messages + persister）
    s2 = AgentState(run_id=run_id, max_steps=10)
    s2.messages = messages
    ctx2 = _ctx(reg, adapter, state=s2)
    s2 = _run_turn("msg-2", s2, ctx2, p)
    _emit_run_end(s2, ctx2.sink)
    messages = s2.messages
    # session 退出：才写 run_end（用最后一轮 status）
    p.log_run_end(s2.status, s2.error)
    p.close()

    recs = list(read_transcript(run_id))
    # 2 user + 2 assistant + 1 run_end，顺序对应两轮
    assert [r["type"] for r in recs] == ["user", "assistant", "user", "assistant", "run_end"]
    assert sum(1 for r in recs if r["type"] == "run_end") == 1
    # 跨轮 messages 累积：两轮 user + 两轮 assistant final 都进 messages（bug1 修复后 final 进 messages）
    roles = [getattr(m, "role", None) for m in messages]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 2


def test_resume_multi_turn_continue():
    """多轮 session transcript（中间轮有 final），崩在末轮工具执行中
    -> resume 重放全部历史 -> continue_loop 续跑只跑 pending，不重复历史工具。
    验证两处关键修复：① 中间轮 final 不设终态（否则 resume 后 transition 非法）；
    ② step_index 重置（否则历史轮次吃掉 max_steps 预算，续跑直接停摆）。"""
    run_id = "t-repl-resume"
    # 轮1 正常 final；轮2 崩在 c2 执行中（c2 无 result）
    _seed(run_id, [
        ("log_user", "msg-1"),
        ("log_assistant", ModelResponse(text="reply-1")),       # 轮1 final（中间轮，不该设终态）
        ("log_user", "msg-2"),
        ("log_assistant", ModelResponse(tool_calls=[
            ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1}),
            ToolCall(call_id="c2", tool_name="echo", arguments={"x": 2}),
        ])),
        ("log_tool_result", ToolResult(call_id="c1", tool_name="echo", ok=True, data={})),
        # c2 无 result -- 崩在 c2 执行中
    ])

    reg, tool_calls = _echo_registry()
    adapter = _ScriptedAdapter([ModelResponse(text="done")])  # 续跑直接 final
    config = AgentConfig(max_steps=10, system_prompt="")

    state = resume(run_id, config, adapter)
    # 重放出 2 轮（2 条 assistant = 2 step）；中间轮 final 没让 status 进终态 -> 可续跑
    assert adapter.call_count == 0               # resume 不调 LLM
    assert len(state.steps) == 2
    assert [c.call_id for c in state.pending_tool_calls] == ["c2"]   # 只有 c2 pending
    assert tool_calls == []                       # resume 没执行工具
    assert not state.is_terminal()                # 修复①：中间轮 final 不设终态

    state2 = continue_loop(state, _ctx(reg, adapter, state=state))
    # 修复②：step_index 重置后能续跑；只重跑 c2（pending），c1 不重跑（有 result）；然后 final
    assert len(tool_calls) == 1
    assert tool_calls[0] == {"x": 2}
    assert adapter.call_count == 1                # 续跑调 1 次 LLM（done）
    assert state2.status == "completed"
    assert len(state2.steps) == 3                 # 2 录制 + 1 续跑 final


# ───────────────────────── 多轮 messages 连续性（bug1 final 进 messages + bug2 跨轮不断裂）─────────────────────────

def test_final_enters_messages():
    """bug1：final 回复进 messages（推翻 Decision 3）。修复前 FINISH 不 append，messages 只有 user；
    修复后 final 也进 messages，多轮下轮能看到上一轮最终回复。final_response 仍设（_emit_run_end 用）。"""
    reg, _ = _echo_registry()
    adapter = _ScriptedAdapter([ModelResponse(text="final-reply")])
    run_id = "t-final-in-msg"
    p = Persister(run_id)
    s = AgentState(run_id=run_id, max_steps=10)
    s = _run_turn("hi", s, _ctx(reg, adapter, state=s), p)
    p.close()
    # final 回复进了 messages（修复前只有 user）
    roles = [getattr(m, "role", None) for m in s.messages]
    assert "assistant" in roles
    assert s.final_response is not None


def test_repl_cross_turn_context():
    """bug2：跨轮 messages 不断裂。append_assistant/tool_result 返回新 list(copy)，REPL 每轮必须
    messages = state.messages 同步，否则下一轮丢失上一轮 assistant + tool_result（user 不丢，in-place）。"""
    reg, _ = _echo_registry()
    adapter = _ScriptedAdapter([
        ModelResponse(tool_calls=[ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})]),
        ModelResponse(text="done"),
    ])
    run_id = "t-cross-turn"
    p = Persister(run_id)
    messages: list = []

    # 轮1：CALL_TOOLS（append_assistant 返回新 list，state.messages 离开共享 messages 对象）
    s1 = AgentState(run_id=run_id, max_steps=10)
    s1.messages = messages
    s1 = _run_turn("msg-1", s1, _ctx(reg, adapter, state=s1), p)
    messages = s1.messages   # ← REPL 同步（去掉这行就复现 bug2：轮2 看不到轮1 的 assistant/tool）

    # 轮2：final
    s2 = AgentState(run_id=run_id, max_steps=10)
    s2.messages = messages
    s2 = _run_turn("msg-2", s2, _ctx(reg, adapter, state=s2), p)
    p.close()

    # 轮2 的 messages 含轮1 的 assistant + tool_result（跨轮不丢）
    roles = [getattr(m, "role", None) for m in s2.messages]
    assert "assistant" in roles          # 轮1 的 assistant(tool_calls)
    assert "tool" in roles               # 轮1 的 tool_result
    assert any(getattr(m, "content", None) == "msg-1"
               for m in s2.messages if getattr(m, "role", None) == "user")
