"""阶段10 多 Agent 协作验收测试。

覆盖(commit 6-10 的机制):
- Agent 抽象 + Orchestrator handoff 链(commit 7-8)
- max_handoffs 上限 + handoff_history 去重(防无限转交,commit 10)
- 后台 subagent fire-and-forget + notify_queue + contextvar 隔离(commit 9)
- Blackboard 共享 state(commit 7)
- 权限隔离:tool list 过滤,handoff 特权化(子 agent 无权再生子 agent,commit 10)
- 多 Agent tracing:span agent_id(commit 10)
- detect_handoff 兼容 mock/openai_compat/ark 三种 tool 结果格式(commit 8)

不依赖真实 LLM:用 _ScriptAdapter(按脚本返回 ModelResponse,继承 BaseModelAdapter 获默认 stream_llm)。
测试用 asyncio.run(...)(同 test_smoke.py 模式,无 pytest-asyncio)。运行(从 code/,3.12 venv):
    python -m pytest tests/test_multi_agent.py -v
"""
import asyncio
import json

from agent.multiagent import (Agent, OrchestratorAgent, WorkerAgent, Blackboard,
    detect_handoff, run_subagent_background, launch_background_subagent)
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.core.models import ModelResponse
from agent.core.messages import Message
from agent.adapters.base import BaseModelAdapter
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.tools.defs import Tool, ToolSpec, ToolCall
from agent.tracing import Tracer
from agent.tools import _runtime_state


# ---- mock adapter ----

class _ScriptAdapter(BaseModelAdapter):
    """按脚本返回 ModelResponse(共享:orchestrator+worker 按调用序消费)。脚本耗尽返回 'done'。"""

    def __init__(self, script):
        super().__init__("", "", "")
        self.script = script
        self.n = 0

    async def call_llm(self, request):
        if self.n < len(self.script):
            r = self.script[self.n]
            self.n += 1
            return r
        return ModelResponse(text="done")

    def append_assistant(self, m, mr):
        return list(m) + [Message(role="assistant", content=mr.text or "")]

    def append_tool_result(self, m, r):
        return list(m) + [Message(role="tool", content=r.text or "")]


class _CountAdapter(BaseModelAdapter):
    """每次 call_llm 计数 +1,返回 'worker#N'。用于数 worker 被 delegate 的次数。"""

    def __init__(self):
        super().__init__("", "", "")
        self.count = 0

    async def call_llm(self, request):
        self.count += 1
        return ModelResponse(text=f"worker#{self.count}")

    def append_assistant(self, m, mr):
        return list(m) + [Message(role="assistant", content=mr.text or "")]

    def append_tool_result(self, m, r):
        return list(m) + [Message(role="tool", content=r.text or "")]


class _RecAdapter(BaseModelAdapter):
    """记录最后一次请求的 tools(验权限过滤:模型看到了哪些工具)。"""

    def __init__(self, resp):
        super().__init__("", "", "")
        self.resp = resp
        self.last_tools = []

    async def call_llm(self, request):
        self.last_tools = request.tools or []
        return self.resp

    def append_assistant(self, m, mr):
        return list(m) + [Message(role="assistant", content=mr.text or "")]

    def append_tool_result(self, m, r):
        return list(m) + [Message(role="tool", content=r.text or "")]


# ---- helpers ----

def _ctx(script, sink=None):
    """造一个 RuntimeContext(_ScriptAdapter + 空 registry + AgentState)。
    sink=None 时不传,用 RuntimeContext 默认 NullSink(显式传 None 会覆盖默认成 None 导致 sink.emit 崩)。"""
    reg = ToolRegistry()
    kw = dict(registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_ScriptAdapter(script), config=AgentConfig(max_steps=5), state=AgentState())
    if sink is not None:
        kw["sink"] = sink
    return RuntimeContext(**kw)


def _dummy_tool(name="search"):
    """造一个非 handoff 的 dummy 工具(权限测试用:worker 应能看到它、看不到 handoff)。"""
    def handler(query=""):
        return {"result": name}
    return Tool(tool_spec=ToolSpec(name=name, description="dummy",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": []}),
        handler=handler)


def _handoff_call(cid, role, context):
    """造一个 handoff 工具调用的 ModelResponse。"""
    return ModelResponse(tool_calls=[ToolCall(call_id=cid, tool_name="handoff",
        arguments={"to_role": role, "context": context})])


# ---- 测试:Agent 抽象(commit 7)----

def test_agent_run_completes():
    """Agent.run 基本路径:mock FINISH -> completed,final_response 正确。"""
    rt = _ctx([ModelResponse(text="agent done")])
    a = Agent(role="coder", tools=[], config=rt.config, runtime=rt)
    s = asyncio.run(a.run("写函数"))
    assert s.status == "completed"
    assert s.final_response.text == "agent done"


# ---- 测试:Orchestrator handoff 链 + Blackboard(commit 7-8)----

def test_orchestrator_handoff_chain_and_blackboard():
    """orchestrator --handoff--> search worker -> orchestrator FINISH;worker 结果写 blackboard。"""
    script = [
        _handoff_call("h1", "search", "找 X"),  # orch iter1: handoff
        ModelResponse(text="orch1"),             # orch iter1: FINISH(收尾本轮)
        ModelResponse(text="找到 X"),            # worker: FINISH
        ModelResponse(text="完成"),              # orch iter2: FINISH
    ]
    rt = _ctx(script)
    search = WorkerAgent(role="search", tools=[], config=rt.config, runtime=rt)
    orch = OrchestratorAgent(runtime=rt, workers=[search], max_handoffs=5)
    bb = Blackboard()
    s = asyncio.run(orch.run("做某事", bb))
    assert s.status == "completed"
    assert s.final_response.text == "完成"
    assert asyncio.run(bb.get("search")) == "找到 X"  # worker 结果回灌 blackboard


def test_orchestrator_multi_worker_chain():
    """多 worker 串行 handoff 链:orch -> search -> coder -> reviewer -> orch FINISH(对标 §6 验收)。
    每轮 delegate 给不同 worker(不同 dedup_key,不触发去重),结果都写 blackboard。"""
    script = [
        _handoff_call("h1", "search", "搜索 X"), ModelResponse(text="orch1"),
        ModelResponse(text="found X"),
        _handoff_call("h2", "coder", "写代码"), ModelResponse(text="orch2"),
        ModelResponse(text="code done"),
        _handoff_call("h3", "reviewer", "审查"), ModelResponse(text="orch3"),
        ModelResponse(text="review ok"),
        ModelResponse(text="all done"),
    ]
    rt = _ctx(script)
    workers = [WorkerAgent(role=r, tools=[], config=rt.config, runtime=rt)
               for r in ("search", "coder", "reviewer")]
    orch = OrchestratorAgent(runtime=rt, workers=workers, max_handoffs=5)
    bb = Blackboard()
    s = asyncio.run(orch.run("做某事", bb))
    assert s.status == "completed"
    assert s.final_response.text == "all done"
    assert asyncio.run(bb.get("search")) == "found X"
    assert asyncio.run(bb.get("coder")) == "code done"
    assert asyncio.run(bb.get("reviewer")) == "review ok"


def test_blackboard_async_rw():
    """Blackboard async 读写 + snapshot(空时空串)。"""
    async def run():
        bb = Blackboard()
        assert bb.snapshot() == ""
        await bb.set("search", "X")
        await bb.set("coder", "Y")
        assert await bb.get("search") == "X"
        snap = bb.snapshot()
        assert "[search] X" in snap and "[coder] Y" in snap
    asyncio.run(run())


# ---- 测试:防无限转交(commit 10)----

def test_max_handoffs_terminates():
    """超过 max_handoffs 自动终止:用不同 context 避开 dedup,验证 delegate 次数 == max_handoffs。"""
    worker_rt = RuntimeContext(registry=ToolRegistry(), tool_executor=ToolExecutor(ToolRegistry()),
        model_adapter=_CountAdapter(), config=AgentConfig(max_steps=5), state=AgentState())
    sw = WorkerAgent(role="search", tools=[], config=worker_rt.config, runtime=worker_rt)
    script = [
        _handoff_call("h1", "search", "c1"), ModelResponse(text="o1"),
        _handoff_call("h2", "search", "c2"), ModelResponse(text="o2"),
        _handoff_call("h3", "search", "c3"), ModelResponse(text="o3"),  # 第3个不该被消费
    ]
    rt = _ctx(script)
    orch = OrchestratorAgent(runtime=rt, workers=[sw], max_handoffs=2)
    s = asyncio.run(orch.run("task"))
    assert worker_rt.model_adapter.count == 2, \
        f"应 delegate 2 次(max_handoffs=2),实际 {worker_rt.model_adapter.count}"
    assert s.status == "completed"


def test_handoff_dedup_terminates():
    """同 (worker, 子任务) 重复 handoff -> dedup 拦,worker 只 delegate 一次。"""
    worker_rt = RuntimeContext(registry=ToolRegistry(), tool_executor=ToolExecutor(ToolRegistry()),
        model_adapter=_CountAdapter(), config=AgentConfig(max_steps=5), state=AgentState())
    sw = WorkerAgent(role="search", tools=[], config=worker_rt.config, runtime=worker_rt)
    script = [
        _handoff_call("h1", "search", "do X"), ModelResponse(text="o1"),  # iter1
        _handoff_call("h2", "search", "do X"), ModelResponse(text="o2"),  # iter2: 同 dedup_key
    ]
    rt = _ctx(script)
    orch = OrchestratorAgent(runtime=rt, workers=[sw], max_handoffs=5)
    asyncio.run(orch.run("task"))
    assert worker_rt.model_adapter.count == 1, \
        f"dedup 应拦第2次,worker 调 {worker_rt.model_adapter.count} 次"


# ---- 测试:后台 subagent(commit 9)----

def test_background_subagent_notification():
    """run_subagent_background 完成 -> notify_queue 收到 (role, final_text)。"""
    rt = _ctx([ModelResponse(text="bg result")])
    worker = WorkerAgent(role="search", tools=[], config=rt.config, runtime=rt)
    q: asyncio.Queue = asyncio.Queue()
    asyncio.run(run_subagent_background(worker, "找 X", q))
    role, text = q.get_nowait()
    assert role == "search" and text == "bg result"


def test_background_contextvar_isolation():
    """后台 subagent(asyncio.Task)不污染父协程 contextvar(current_step_id)。

    父设 current_step_id=SENTINEL,后台 subagent 跑(_run_steps 会 set 它),await 后父仍 SENTINEL。
    验 Step 5 的 contextvar 隔离(asyncio.Task 复制 context)对标 CC AsyncLocalStorage。
    """
    async def check():
        _runtime_state.current_step_id.set("PARENT_SENTINEL")
        rt = _ctx([ModelResponse(text="iso")])
        worker = WorkerAgent(role="search", tools=[], config=rt.config, runtime=rt)
        q: asyncio.Queue = asyncio.Queue()
        t = launch_background_subagent(worker, "iso task", q)
        await t
        assert _runtime_state.current_step_id.get() == "PARENT_SENTINEL", \
            _runtime_state.current_step_id.get()

    _runtime_state.reset()
    asyncio.run(check())


def test_orchestrator_launch_background():
    """OrchestratorAgent.launch_background 经 runtime.notify_queue 启动后台 worker,结果回 queue。"""
    async def run():
        q: asyncio.Queue = asyncio.Queue()
        rt = _ctx([ModelResponse(text="orch bg")])
        rt.notify_queue = q
        sw = WorkerAgent(role="search", tools=[], config=rt.config, runtime=rt)
        orch = OrchestratorAgent(runtime=rt, workers=[sw])
        await orch.launch_background("search", "t")
        role, text = q.get_nowait()
        assert role == "search" and text == "orch bg"
    asyncio.run(run())


# ---- 测试:权限隔离(commit 10)----

def test_permission_tool_filter():
    """orchestrator 只见 handoff;worker(含 tools=[] 全允许)排除 handoff(子 agent 无权再生子 agent)。"""
    reg = ToolRegistry()
    reg.register(_dummy_tool("search"))
    # orchestrator: allowed_tools=["handoff"] -> 只见 handoff
    rt = RuntimeContext(registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_RecAdapter(ModelResponse(text="done")), config=AgentConfig(max_steps=5), state=AgentState())
    orch = OrchestratorAgent(runtime=rt, workers=[])  # __init__ 注册 handoff
    asyncio.run(orch.run("t"))
    assert [t.name for t in rt.model_adapter.last_tools] == ["handoff"], \
        rt.model_adapter.last_tools
    # worker tools=[](全允许)也应排除 handoff,只见 search
    rt2 = RuntimeContext(registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_RecAdapter(ModelResponse(text="done")), config=AgentConfig(max_steps=5), state=AgentState())
    w = WorkerAgent(role="search", tools=[], config=rt2.config, runtime=rt2)
    asyncio.run(w.run("t"))
    wtools = [t.name for t in rt2.model_adapter.last_tools]
    assert "handoff" not in wtools and "search" in wtools, wtools


# ---- 测试:多 Agent tracing(commit 10)----

def test_tracing_span_agent_id():
    """多 Agent tracing:span 带 agent_id(orchestrator/worker 各自的 span,题17)。"""
    _runtime_state.reset()
    tracer = Tracer("tr_run")
    reg = ToolRegistry()
    reg.register(_dummy_tool("search"))
    script = [_handoff_call("h1", "search", "do X"), ModelResponse(text="o1"),
              ModelResponse(text="w"), ModelResponse(text="final")]
    rt = RuntimeContext(registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_ScriptAdapter(script), config=AgentConfig(max_steps=5),
        state=AgentState(), sink=tracer)
    sw = WorkerAgent(role="search", tools=[], config=rt.config, runtime=rt)
    orch = OrchestratorAgent(runtime=rt, workers=[sw])
    asyncio.run(orch.run("task"))
    aids = {s.attrs.get("agent_id") for s in tracer.trace.spans if s.attrs.get("agent_id")}
    assert "orchestrator" in aids and "search" in aids, aids


# ---- 测试:detect_handoff 多适配器格式(commit 8)----

# ---- 测试:Task 工具(主 agent 派子 agent,CC 小弟模型)----

def test_task_tool_subagent():
    """Task 工具:主 agent 调 task -> 子 agent 跑子任务 -> 结果回填 tool result -> 主 agent FINISH。

    验证 CC 小弟模型:主 agent 调 task 工具,_run_steps 拦截 __subagent__ 标记 -> 异步跑子 agent
    (复用 Agent.run)-> 子 agent 的最终回答作为 task 工具结果回填 -> 主 agent 据此 FINISH。
    """
    from agent.agentloop import _run_turn
    from agent.tools.task_tool import make_task_tool
    reg = ToolRegistry()
    reg.register(make_task_tool())
    # 脚本(共享 adapter,按调用序):主 agent 调 task -> 子 agent FINISH -> 主 agent FINISH
    script = [
        ModelResponse(tool_calls=[ToolCall(call_id="t1", tool_name="task",
            arguments={"description": "查 X", "prompt": "调查 X 是什么"})]),
        ModelResponse(text="X 是某个东西"),  # 子 agent FINISH
        ModelResponse(text="基于子 agent: X 是某个东西"),  # 主 agent FINISH
    ]
    state = AgentState()
    ctx = RuntimeContext(registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=_ScriptAdapter(script), config=AgentConfig(max_steps=5), state=state)
    s = asyncio.run(_run_turn("查一下 X", state, ctx, persister=None))
    assert s.status == "completed"
    assert "X 是某个东西" in (s.final_response.text or "")
    # 子 agent 结果作为 task 工具结果回填到 messages
    tool_msgs = [m for m in s.messages if getattr(m, "role", None) == "tool"]
    assert any("X 是某个东西" in (m.content if isinstance(m.content, str) else str(m.content))
               for m in tool_msgs), "子 agent 结果未回填"


def test_detect_handoff_multi_adapter():
    """detect_handoff 兼容 mock(str)/openai_compat(dict['content'])/ark(dict['output']) 三种格式。"""
    def hj(role, ctx):
        return json.dumps({"ok": True, "tool": "handoff",
                           "data": {"to_role": role, "context": ctx}}, ensure_ascii=False)

    # mock: content 是 str
    h = detect_handoff(AgentState(messages=[Message(role="tool", content=hj("search", "找X"))]))
    assert h and h.to_role == "search" and h.context == "找X"
    # openai_compat: content 是 dict {"role":"tool",...,"content": <text>}
    h = detect_handoff(AgentState(messages=[Message(role="tool",
        content={"role": "tool", "tool_call_id": "c", "content": hj("coder", "写")})]))
    assert h and h.to_role == "coder" and h.context == "写"
    # ark: content 是 dict {"type":"function_call_output",...,"output": <text>}, role=user
    h = detect_handoff(AgentState(messages=[Message(role="user",
        content={"type": "function_call_output", "call_id": "c", "output": hj("reviewer", "查")})]))
    assert h and h.to_role == "reviewer" and h.context == "查"
    # 非 handoff 工具结果 -> None
    assert detect_handoff(AgentState(messages=[Message(role="tool",
        content=json.dumps({"ok": True, "tool": "read_file", "data": "x"}))])) is None
