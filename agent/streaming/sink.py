# EventSink：流式事件的观察者接口。
#
# 适配器（底层 delta）、agentloop（生命周期）、ToolExecutor（工具执行）都往同一个 sink
# 推事件；UI 层只需实现 emit()。对应 claude-code「query engine 把 message 推给 UI store」的模型：
# 数据生产者与渲染者解耦，多个 sink 可组合（如同时打印 + 写 trace）。
from abc import ABC, abstractmethod

from .events import StreamEvent


class EventSink(ABC):
    """所有事件汇入点。生产者调 emit(event)，消费者在 emit 里渲染/记录。"""

    @abstractmethod
    def emit(self, event: StreamEvent) -> None: ...


class NullSink(EventSink):
    """默认 sink：丢弃所有事件。

    测试与编程式调用用它 -> 流式对它们完全透明（不产生任何 IO）。
    """

    def emit(self, event: StreamEvent) -> None:
        pass


class CompositeSink(EventSink):
    """组合多个 sink，事件广播给每一个。

    例：CompositeSink(StreamingPrinter(), TraceSink()) -> 边打印边写 trace。
    阶段 9 tracing 复用本机制。
    """

    def __init__(self, *sinks: EventSink):
        self.sinks = sinks

    def emit(self, event: StreamEvent) -> None:
        for s in self.sinks:
            s.emit(event)
