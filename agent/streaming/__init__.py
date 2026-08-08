# streaming 子包：流式事件 + sink（+ 渲染器）。
#
# 本包是流式输出的横切层：adapter / agentloop / ToolExecutor 都向 EventSink 推事件，
# UI 层（StreamingPrinter）只实现一个接口即可渲染。详见 docs/topics/streaming-dev-plan.md。
from .events import (
    StreamEvent,
    AssistantMessage, ToolResultMessage,
    RunStart, StepStart, StepEnd, RunEnd, ToolStart, ToolEnd, TaskNotification,
    TextDelta, ToolCallStart, ToolCallDelta, ToolCallEnd, MessageEnd,
    is_web_event,
)
from .sink import EventSink, NullSink, CompositeSink

# 注意:EventStore 不在此 eager import——它依赖 persist.paths,而 tools.registry -> streaming.events
# 这条边会在 core 初始化早期触发 persist -> core 的循环(core/models.py -> tools.defs)。调用点
# 直连子模块(from agent.streaming.event_store import EventStore),与 agentloop/server 现状一致。

__all__ = [
    "StreamEvent",
    "AssistantMessage", "ToolResultMessage",
    "RunStart", "StepStart", "StepEnd", "RunEnd", "ToolStart", "ToolEnd", "TaskNotification",
    "TextDelta", "ToolCallStart", "ToolCallDelta", "ToolCallEnd", "MessageEnd",
    "is_web_event",
    "EventSink", "NullSink", "CompositeSink",
]
