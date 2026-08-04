# tracing/tracer.py - Tracer:EventSink 实现,把事件流转成 span 树(阶段9 任务1)
# 复用 streaming 事件流(RunStart/StepStart/ToolStart/ToolEnd/StepEnd/RunEnd),不新挂载点。
# 挂法:CompositeSink(printer, tracer) -> printer 照常渲染,tracer 同步收 span。
#
# 栈维护 run/step span;tool span 按 call_id 存 dict(并发工具 as_completed 完成序乱,不能靠栈顶)。
# commit 10:span attrs 加 agent_id(读 _runtime_state.agent_id contextvar,Agent.run 时设),
# trace 树可看出 agent 间流转(orchestrator/worker 各自的 span,题17)。
import time
import uuid

from ..streaming.sink import EventSink
from ..streaming.events import (RunStart, StepStart, StepEnd, RunEnd,
    ToolStart, ToolEnd, MessageEnd)
from ..tools import _runtime_state  # commit 10:读 agent_id contextvar 写进 span
from .span import Span, Trace


class Tracer(EventSink):
    """EventSink 实现:收生命周期事件 -> 建 span -> trace。

    - RunStart/StepStart:push 到栈(parent=栈顶)
    - ToolStart:parent=栈顶(step span),span 存 _tool_spans[call_id](不进栈,防并发)
    - ToolEnd/StepEnd/RunEnd:按 type/call_id 找 span finish(pop 栈)
    - RunEnd:flush trace 到 store(若配)
    - commit 10:每个 span 的 attrs 带 agent_id(若在 Agent.run 内),多 Agent tracing
    """

    def __init__(self, run_id: str, trace: Trace | None = None, store=None):
        self.run_id = run_id
        self.trace = trace or Trace(run_id=run_id)
        self.store = store  # TraceStore,可选(None=只内存,测试用)
        self._stack: list[Span] = []          # run/step span
        self._tool_spans: dict[str, Span] = {}  # call_id -> span(并发工具)

    def _attrs(self, **extra) -> dict:
        """构造 span attrs:extra + 当前 agent_id(若在 Agent.run 内,多 Agent tracing 题17)。

        单 agent / REPL 直调 _run_turn 时 agent_id contextvar 为 None,不加(保持 span 干净)。
        """
        d = dict(extra)
        aid = _runtime_state.agent_id.get()
        if aid is not None:
            d["agent_id"] = aid
        return d

    def emit(self, event) -> None:
        match event:
            case RunStart(run_id):
                span = Span(span_id=str(uuid.uuid4()), parent_id=None,
                            type="run", name=run_id, start=time.perf_counter(),
                            attrs=self._attrs())
                self._stack.append(span)
                self.trace.add(span)

            case StepStart(step_index):
                parent = self._stack[-1] if self._stack else None
                span = Span(span_id=str(uuid.uuid4()),
                            parent_id=parent.span_id if parent else None,
                            type="step", name=str(step_index),
                            start=time.perf_counter(),
                            attrs=self._attrs())
                self._stack.append(span)
                self.trace.add(span)

            case ToolStart(call_id, tool_name, arguments):
                parent = self._stack[-1] if self._stack else None
                span = Span(span_id=str(uuid.uuid4()),
                            parent_id=parent.span_id if parent else None,
                            type="tool", name=tool_name,
                            start=time.perf_counter(),
                            attrs=self._attrs(call_id=call_id))
                self._tool_spans[call_id] = span
                self.trace.add(span)

            case ToolEnd(call_id, tool_name, ok, elapsed_ms, error_type, summary):
                span = self._tool_spans.pop(call_id, None)
                if span:
                    span.finish(ok=ok, elapsed_ms=elapsed_ms,
                                error_type=error_type, summary=summary)

            case StepEnd(step_index):
                if self._stack and self._stack[-1].type == "step":
                    self._stack.pop().finish()

            case RunEnd(status, final_text, error):
                if self._stack and self._stack[-1].type == "run":
                    span = self._stack.pop()
                    span.finish(status=status)
                    if self.store:
                        self.store.write(self.trace)

            case MessageEnd(stop_reason, usage):
                # 记 usage 到当前 step span(MetricsCollector 聚合 token 成本)
                if self._stack and self._stack[-1].type == "step" and usage is not None:
                    self._stack[-1].attrs["usage"] = {
                        "input_tokens": getattr(usage, "input_tokens", 0),
                        "output_tokens": getattr(usage, "output_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                        "cached_tokens": getattr(usage, "cached_tokens", 0),
                    }

            case _:
                pass  # TextDelta/ThinkingDelta/ToolCall*/MessageEnd:不建 span
