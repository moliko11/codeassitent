# streaming/sse_sink.py - SSE 桥接:EventSink -> asyncio.Queue
#
# loop 已 async(agentloop.py:484),emit 仍同步(sink.py:15)。本 sink 把事件 put_nowait 到
# asyncio.Queue,SSE 端点 async 消费。loop 协程内调 put_nowait 不阻塞,天然线程边界。
# 对齐 web-app-plan §3 / chat-template-integration §6。
import asyncio

from .sink import EventSink
from .events import StreamEvent


class SSESink(EventSink):
    """把流式事件推到 asyncio.Queue,供 SSE 端点 `await q.get()` 消费。

    emit 同步(在 loop 协程内被调),`put_nowait` 不阻塞事件循环。
    一个 turn 一个 SSESink + queue;run 结束(RunEnd)端点 break。
    """

    def __init__(self, q: asyncio.Queue):
        self.q = q

    def emit(self, event: StreamEvent) -> None:
        self.q.put_nowait(event)
