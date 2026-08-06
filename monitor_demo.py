"""监控 M1 数据层 demo(无 API):用脚本 adapter 跑 2 个假 run,展示
run_meta.json 侧车 + list_runs() + read_run_report() + aggregate_stats() 的真实输出。

运行(从 code/ 目录,3.12 venv 激活后):python monitor_demo.py
不污染真实 persist/runs -- 用临时目录。
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Windows 默认 stdout 是 GBK,print 中文标签会乱码;切 UTF-8(agentloop 同款处理)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 必须在 import agentloop 之前把 PERSIST_ROOT 指到临时目录(坑6:相对路径)
import agent.persist.paths as _paths
_paths.PERSIST_ROOT = Path(tempfile.mkdtemp()) / "runs"

from agent.agentloop import agentloop                       # noqa: E402
from agent.runtime import RuntimeContext                     # noqa: E402
from agent.config.config import AgentConfig                  # noqa: E402
from agent.core.state import AgentState                      # noqa: E402
from agent.core.models import ModelResponse, TokenUsage      # noqa: E402
from agent.adapters.base import BaseModelAdapter             # noqa: E402
from agent.core.messages import Message                      # noqa: E402
from agent.tools.defs import Tool, ToolCall, ToolSpec        # noqa: E402
from agent.tools.registry import ToolRegistry, ToolExecutor  # noqa: E402
from agent.streaming.sink import NullSink                    # noqa: E402
from agent.persist import list_runs, read_run_report         # noqa: E402
from agent.persist.paths import run_meta_path                # noqa: E402
from agent.tracing import aggregate_stats                    # noqa: E402


class _Adapter(BaseModelAdapter):
    """按脚本返回带 usage 的 ModelResponse(usage 经 stream_llm -> MessageEnd -> Tracer 记进 step span)。"""
    def __init__(self, script):
        super().__init__("", "", "")
        self.script = script
        self.i = 0

    async def call_llm(self, req):
        r = self.script[self.i]
        self.i += 1
        return r

    def append_assistant(self, m, mr):
        return [*m, Message(role="assistant", content=mr.text or "")]

    def append_tool_result(self, m, r):
        return [*m, Message(role="tool", content=r.text or "")]


def _echo_registry():
    reg = ToolRegistry()

    def handler(**kw):
        return {"echoed": kw}

    reg.register(Tool(tool_spec=ToolSpec(
        name="echo", description="echo back", input_schema={"type": "object"}),
        handler=handler))
    return reg


def _ctx(adapter, model, reg=None):
    reg = reg or ToolRegistry()
    return RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg),
        model_adapter=adapter,
        config=AgentConfig(max_steps=10, system_prompt="", model=model),
        state=AgentState(), sink=NullSink(), persist=True,
    )


def main():
    print("=" * 70)
    print("M1 数据层 demo:跑 2 个 run(脚本 adapter,无 API),展示侧车 + 聚合")
    print("=" * 70)

    # ── run A:1 工具轮(echo)+ final 轮,两个 step 各有 usage ──
    reg = _echo_registry()
    state_a = asyncio.run(agentloop("hi", _ctx(_Adapter([
        ModelResponse(tool_calls=[ToolCall(call_id="c1", tool_name="echo", arguments={"x": 1})],
                      usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)),
        ModelResponse(text="done", usage=TokenUsage(input_tokens=20, output_tokens=10, total_tokens=30)),
    ]), model="deepseek-v4-pro", reg=reg)))

    # ── run B:final only ──
    state_b = asyncio.run(agentloop("yo", _ctx(_Adapter([
        ModelResponse(text="ok", usage=TokenUsage(input_tokens=5, output_tokens=5, total_tokens=10))]),
        model="qwen")))

    # ── 1. 看 run A 的 run_meta.json 侧车(RunEnd 自动落盘的摘要)──
    print("\n[1] run A 的 run_meta.json 侧车内容:")
    print(json.dumps(json.loads(run_meta_path(state_a.run_id).read_text(encoding="utf-8")),
                     ensure_ascii=False, indent=2))

    # ── 2. list_runs():列所有 run(读侧车,O(1))──
    print("\n[2] list_runs() -- 所有 run 摘要(按 started_at 倒序):")
    for r in list_runs():
        print(f"  {r['run_id'][:8]}.. status={r['status']:<10} model={r['model']:<16} "
              f"token_in={r['token_input']:<4} token_out={r['token_output']:<4} "
              f"token_total={r['token_total']:<5} tools={r['tool_count']} ok={r['tool_success_rate']:.0%}")

    # ── 3. read_run_report():单 run 指标(load trace 聚合)──
    print("\n[3] read_run_report(run A) -- 从 trace 重新聚合(token = step usage 之和):")
    rep = read_run_report(state_a.run_id)
    print(f"  status={rep.status} steps={rep.step_count} tools={rep.tool_count} "
          f"token_in={rep.token_input} token_out={rep.token_output} token_total={rep.token_total}")

    # ── 4. aggregate_stats():跨 run 聚合 ──
    print("\n[4] aggregate_stats(list_runs()) -- 跨 run 聚合:")
    s = aggregate_stats(list_runs())
    print(f"  run_count={s.run_count}")
    print(f"  total_token={s.total_token} (in={s.total_token_input} out={s.total_token_output})")
    print(f"  avg_tool_success_rate={s.avg_tool_success_rate:.0%}")
    print(f"  by_model={json.dumps(s.by_model, ensure_ascii=False)}")
    print(f"  by_day={json.dumps(s.by_day, ensure_ascii=False)}")
    print(f"  total_cost={s.total_cost}  (TODO §8,本期不算钱)")

    print("\n" + "=" * 70)
    print("看完即焚:临时目录", _paths.PERSIST_ROOT, "(demo 退出自动留,可手动删)")


if __name__ == "__main__":
    main()
