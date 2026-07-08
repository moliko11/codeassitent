# streaming 子包：流式事件 + sink（+ 渲染器）。
#
# 本包是流式输出的横切层：adapter / agentloop / ToolExecutor 都向 EventSink 推事件，
# UI 层（StreamingPrinter）只实现一个接口即可渲染。详见 docs/streaming-dev-plan.md。
from .events import (
    StreamEvent,
    RunStart, StepStart, StepEnd, RunEnd, ToolStart, ToolEnd,
    TextDelta, ToolCallStart, ToolCallDelta, ToolCallEnd, MessageEnd,
)
from .sink import EventSink, NullSink, CompositeSink

__all__ = [
    "StreamEvent",
    "RunStart", "StepStart", "StepEnd", "RunEnd", "ToolStart", "ToolEnd",
    "TextDelta", "ToolCallStart", "ToolCallDelta", "ToolCallEnd", "MessageEnd",
    "EventSink", "NullSink", "CompositeSink",
]
