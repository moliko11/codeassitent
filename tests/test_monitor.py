"""监控后台 M1(数据层)验收测试。对齐 monitor-dashboard-plan §9 M1:
- list_runs() 返回所有 run 的 meta(有侧车读侧车,没侧车退化扫 transcript)
- 新跑一个 run,run_meta.json 落盘且含 token_input/output/total
- read_run_report(run_id) 返回的 RunReport token = step span usage 之和(坑1:精确值)
- aggregate_stats(list_runs()) 输出总 token / run 数 / 平均成功率 / by_day / by_model

不依赖真实 LLM,用 _UsageAdapter(按脚本返回带 usage 的 ModelResponse)。
运行(从 code/ 目录,3.12 venv):python -m pytest tests/test_monitor.py -v
"""
import asyncio
import json
import time

import pytest

from agent.agentloop import agentloop
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState
from agent.core.models import ModelResponse, TokenUsage
from agent.adapters.base import BaseModelAdapter
from agent.core.messages import Message
from agent.tools.defs import Tool, ToolCall, ToolSpec
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.streaming.sink import NullSink
from agent.persist import Persister, list_runs, read_run_report
from agent.persist import paths as persist_paths
from agent.persist.paths import run_meta_path
from agent.tracing import aggregate_stats


# ───────────────────────── 测试夹具与 helpers ─────────────────────────

@pytest.fixture(autouse=True)
def _tmp_persist_root(tmp_path, monkeypatch):
    """把 PERSIST_ROOT 指到 tmp_path,测试落盘不污染 code/persist(同 test_persist)。"""
    monkeypatch.setattr(persist_paths, "PERSIST_ROOT", tmp_path / "runs")


class _UsageAdapter(BaseModelAdapter):
    """按脚本顺序返回 ModelResponse(可带 usage),计数 call_llm。
    usage 经 stream_llm 默认实现 -> MessageEnd -> Tracer 记进 step span attrs["usage"]。"""
    def __init__(self, script: list[ModelResponse]):
        super().__init__(api_key="", base_url="", model="")
        self.script = script
        self.i = 0

    async def call_llm(self, request):
        resp = self.script[self.i]
        self.i += 1
        return resp

    def append_assistant(self, messages, model_response):
        new = list(messages)
        new.append(Message(role="assistant", content=model_response.text or ""))
        return new

    def append_tool_result(self, messages, result):
        new = list(messages)
        new.append(Message(role="tool", content=result.text or ""))
        return new


def _echo_registry():
    """注册一个 echo 工具(成功),用于构造有工具调用的 run(测 tool_success_rate)。"""
    reg = ToolRegistry()

    def handler(**kwargs):
        return {"echoed": kwargs}

    reg.register(Tool(
        tool_spec=ToolSpec(name="echo", description="echo back arguments",
                           input_schema={"type": "object"}),
        handler=handler,
    ))
    return reg


def _ctx(adapter, state=None, persist=True, model="test-model", reg=None, system_prompt=""):
    return RuntimeContext(
        registry=reg or ToolRegistry(),
        tool_executor=ToolExecutor(reg or ToolRegistry()),
        model_adapter=adapter,
        config=AgentConfig(max_steps=10, system_prompt=system_prompt, model=model),
        state=state or AgentState(),
        sink=NullSink(),
        persist=persist,
    )


def _seed_transcript_only(run_id: str, status="failed"):
    """落一个只有 transcript(无 run_meta 无 trace)的 run,模拟崩了/老 run(坑2 退化场景)。"""
    p = Persister(run_id)
    p.log_user("hi")
    p.log_assistant(ModelResponse(text="boom"))
    p.log_run_end(status, None)
    p.close()


# ───────────────────────── run_meta 侧车落盘 ─────────────────────────

def test_run_meta_written_with_tokens():
    """新跑一个 run(persist=True)-> run_meta.json 落盘,含精确 token(坑1)+ status + model。"""
    adapter = _UsageAdapter([
        ModelResponse(text="done", usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150, cached_tokens=80)),
    ])
    state = asyncio.run(agentloop("hi", _ctx(adapter)))

    meta_p = run_meta_path(state.run_id)
    assert meta_p.exists(), "run_meta.json 应在 RunEnd 落盘"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    assert meta["run_id"] == state.run_id
    assert meta["status"] == "completed"
    assert meta["token_input"] == 100
    assert meta["token_output"] == 50
    assert meta["token_total"] == 150          # 坑1:LLM 返回的精确 usage,非 count_message_tokens 估算
    assert meta["token_cached"] == 80          # 缓存命中(adapter 填 -> tracer 记 -> metrics 聚合 -> meta 存)
    assert meta["model"] == "test-model"        # §8 cost 用
    assert meta["started_at"] > 0               # 墙钟(by_day 需要真日期,state.created_at 是 perf_counter 不行)
    assert meta["system_prompt"] == ""          # 按会话存(此处 _ctx 用空 system_prompt)


def test_run_meta_stores_system_prompt():
    """run_meta 按会话存 system_prompt(不同 run 可能用不同提示词),详情页分层展示用。"""
    sp = "## 段一\n内容一\n## 段二(对齐 X)\n内容二"
    adapter = _UsageAdapter([ModelResponse(text="done", usage=TokenUsage(1, 1, 2))])
    state = asyncio.run(agentloop("hi", _ctx(adapter, system_prompt=sp)))
    meta = json.loads(run_meta_path(state.run_id).read_text(encoding="utf-8"))
    assert meta["system_prompt"].startswith(sp)     # 静态核心在前(动态组装后 sp 仍是前缀)
    assert "## 语言" in meta["system_prompt"]        # 动态段已追加(build_system_prompt)
    assert meta["system_prompt"].count("## ") == 5   # 静态 2 + 动态 3(语言/环境/工具结果清理)


def test_no_run_meta_when_not_persisted():
    """persist=False 不落盘(测试/非持久 run 不污染,与 transcript/trace 同 gate)。"""
    adapter = _UsageAdapter([ModelResponse(text="done", usage=TokenUsage(1, 1, 2))])
    state = asyncio.run(agentloop("hi", _ctx(adapter, persist=False)))
    # 直构路径检查,不走 run_dir(避免读检查触发 mkdir 副作用)
    assert not (persist_paths.PERSIST_ROOT / state.run_id / "run_meta.json").exists()


# ───────────────────────── read_run_report(单 run 指标) ─────────────────────────

def test_read_run_report_matches_usage_sum():
    """read_run_report = load trace -> MetricsCollector。token = step span usage 之和(坑1)。
    多 step(工具轮 + final 轮)usage 累加。"""
    reg = _echo_registry()
    adapter = _UsageAdapter([
        ModelResponse(tool_calls=[ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})],
                      usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)),
        ModelResponse(text="done", usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30)),
    ])
    state = asyncio.run(agentloop("hi", _ctx(adapter, reg=reg)))

    rep = read_run_report(state.run_id)
    assert rep is not None
    assert rep.token_input == 120               # 100 + 20(两 step 累加)
    assert rep.token_output == 60               # 50 + 10
    assert rep.token_total == 180               # 150 + 30
    assert rep.step_count == 2
    assert rep.tool_count == 1 and rep.tool_success_rate == 1.0
    # 与 run_meta 侧车的 token 一致(同源:都从 trace 聚合)
    meta = json.loads(run_meta_path(state.run_id).read_text(encoding="utf-8"))
    assert meta["token_total"] == rep.token_total


def test_read_run_report_none_when_no_trace():
    """trace.jsonl 不存在(崩了没 RunEnd,坑2)-> None。"""
    _seed_transcript_only("t-no-trace", status="failed")  # 只有 transcript,无 trace
    assert read_run_report("t-no-trace") is None
    assert read_run_report("never-existed") is None


# ───────────────────────── list_runs(侧车 + 退化) ─────────────────────────

def test_list_runs_sidecar_and_fallback():
    """有侧车的 run 读侧车(含 token);没侧车的 run 退化扫 transcript(只 status,token=0)。"""
    # run A:真实跑一次,有侧车(坑3:O(1) 读侧车,不 load trace)
    adapter = _UsageAdapter([ModelResponse(text="done", usage=TokenUsage(100, 50, 150))])
    state_a = asyncio.run(agentloop("hi", _ctx(adapter)))
    # run B:只有 transcript(无侧车无 trace),退化扫 run_end 拿 status(坑2)
    _seed_transcript_only("t-fallback", status="failed")

    runs = list_runs()
    assert len(runs) == 2
    # 按 started_at 倒序:A 有墙钟 started_at(>0),B 退化 started_at=0 -> A 在前
    assert runs[0]["run_id"] == state_a.run_id
    assert runs[0]["token_total"] == 150          # 侧车:有 token
    assert runs[0]["status"] == "completed"
    assert runs[1]["run_id"] == "t-fallback"
    assert runs[1]["status"] == "failed"          # 退化:扫 run_end 拿到 status
    assert runs[1]["token_total"] == 0            # 退化:transcript 无 usage,token 拿不到


def test_list_runs_empty_when_no_root():
    """PERSIST_ROOT 不存在 -> 空列表(不报错)。"""
    assert list_runs() == []


def test_scan_transcript_tail_running_when_no_run_end():
    """transcript 有内容但无 run_end(在跑/崩在 RunEnd 前)-> 退化 status='running'。"""
    p = Persister("t-live")
    p.log_user("hi")
    p.log_assistant(ModelResponse(text="thinking..."))
    p.close()                                    # 不写 run_end
    runs = {r["run_id"]: r for r in list_runs()}
    assert runs["t-live"]["status"] == "running"
    assert runs["t-live"]["token_total"] == 0


# ───────────────────────── aggregate_stats(跨 run 聚合) ─────────────────────────

def test_aggregate_stats():
    """aggregate_stats(list_runs()):总 token / run 数 / 平均成功率 / by_day / by_model。"""
    reg = _echo_registry()
    # run 1:1 工具(成功)+ final,两 step usage 150+30=180,model=test-model
    asyncio.run(agentloop("hi", _ctx(_UsageAdapter([
        ModelResponse(tool_calls=[ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})],
                      usage=TokenUsage(100, 50, 150, 60)),
        ModelResponse(text="done", usage=TokenUsage(20, 10, 30)),
    ]), reg=reg)))
    # run 2:final only,usage 5/5/10(cached=5),model=other-model(无工具 -> success_rate=0)
    asyncio.run(agentloop("yo", _ctx(_UsageAdapter([
        ModelResponse(text="ok", usage=TokenUsage(5, 5, 10, 5))]), model="other-model")))

    s = aggregate_stats(list_runs())
    assert s.run_count == 2
    assert s.total_token_input == 125            # 100+20+5
    assert s.total_token_output == 65            # 50+10+5
    assert s.total_token == 190                  # 180+10(坑4 fallback 不触发,total 都 >0)
    assert s.total_token_cached == 65            # 60 + 0 + 5
    assert abs(s.avg_cache_hit_rate - 65/125) < 0.01   # 65/125 ≈ 0.52
    # by_model
    assert s.by_model["test-model"]["token"] == 180
    assert s.by_model["test-model"]["runs"] == 1
    assert s.by_model["other-model"]["token"] == 10
    # by_day:两个 run 都是今天(墙钟 started_at)
    today = time.strftime("%Y-%m-%d", time.localtime())
    assert today in s.by_day
    assert s.by_day[today]["runs"] == 2
    assert s.by_day[today]["token"] == 190
    # avg_tool_success_rate:run1=1.0(1 工具成功),run2=0.0(无工具)-> 0.5
    assert s.avg_tool_success_rate == 0.5


def test_aggregate_stats_total_fallback():
    """坑4:total=0/缺失时用 input+output 兜底,别直接信 total。"""
    runs = [
        {"token_input": 100, "token_output": 50, "token_total": 0,    # total=0 -> 兜底 150
         "tool_success_rate": 1.0, "started_at": time.time(), "model": "m"},
        {"token_input": 30, "token_output": 20, "token_total": 50,     # total 正常
         "tool_success_rate": 0.0, "started_at": time.time(), "model": "m"},
    ]
    s = aggregate_stats(runs)
    assert s.total_token == 200                  # 150(兜底) + 50


def test_aggregate_stats_empty():
    """空列表 -> 零值,不报错(除零保护)。"""
    s = aggregate_stats([])
    assert s.run_count == 0
    assert s.total_token == 0
    assert s.avg_tool_success_rate == 0.0
    assert s.by_day == {} and s.by_model == {}


# ───────────────────────── REPL(会话级)侧车落盘 ─────────────────────────

def test_repl_run_meta_on_clean_exit(monkeypatch):
    """REPL(run_agent_loop)输入 exit 正常退出 -> run_meta.json 落盘。
    这是用户实际用的入口(python -m agent.agentloop);mock input 模拟一轮对话 + exit。
    关键:不 exit(关终端/Ctrl+C)-> 不写侧车(坑2:无 run_end),与本测试对照。"""
    import builtins
    from agent.agentloop import run_agent_loop

    inputs = iter(["你好", "exit"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(inputs))
    reg = ToolRegistry()
    adapter = _UsageAdapter([ModelResponse(text="hi", usage=TokenUsage(10, 5, 15))])
    config = AgentConfig(max_steps=10, system_prompt="", model="test-model")
    asyncio.run(run_agent_loop(reg, adapter, ToolExecutor(reg), config=config))

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"      # REPL 用 last_state.status(真相,非 rep.status='unknown')
    assert runs[0]["token_total"] == 15           # REPL token = step usage 之和(正确,坑1)
    assert runs[0]["model"] == "test-model"


def test_repl_run_meta_crash_safe(monkeypatch):
    """崩了(非正常 exit)也有 run_meta:每轮 _do_turn 增量落盘,崩在下一轮前保留最近完成的轮。
    模拟:第一轮正常 -> 第二次 input 抛 EOFError(模拟关终端/崩)。run_meta 应仍有第一轮的 token。"""
    import builtins
    from agent.agentloop import run_agent_loop

    inputs = iter(["你好"])

    def fake_input(*a, **k):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError("simulated crash / close terminal")

    monkeypatch.setattr(builtins, "input", fake_input)
    reg = ToolRegistry()
    adapter = _UsageAdapter([ModelResponse(text="hi", usage=TokenUsage(10, 5, 15))])
    config = AgentConfig(max_steps=10, system_prompt="", model="test-model")
    with pytest.raises(EOFError):
        asyncio.run(run_agent_loop(reg, adapter, ToolExecutor(reg), config=config))

    # 崩了,但第一轮 _do_turn 已增量落盘 run_meta
    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["token_total"] == 15           # 第一轮的 token 保留
    assert runs[0]["status"] == "completed"

