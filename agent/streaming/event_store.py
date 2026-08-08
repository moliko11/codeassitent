# streaming/event_store.py - 前端事件流落盘(EventStore)
#
# 把"给前端的事件流"(web 契约 = is_web_event)逐条追加到 persist/runs/<run_id>/events.jsonl,
# 与 transcript.jsonl(消息事实)/ trace.jsonl(观测 span)/ run_meta.json(监控摘要)并列,
# 补上"前端消费过什么"的耐久层。价值:前端历史恢复可精确重放事件(不再从 transcript 反推);
# 监控/调试能回看事件契约本身。
#
# 实现:EventSink(挂 CompositeSink,零侵入主循环)。内部按 is_web_event 过滤,只写 web 契约事件;
# 每条 JSONL = {"ts": 墙钟, "type": 事件类名, **事件字段}(形状对齐 server._event_to_dict 的 SSE 输出,
# 前端 eventReducer 按 type 分发,可直接用同一 reducer 重放)。
# 惰性开文件:首条 web 事件才建 events.jsonl(纯低层事件的 run 不留空文件)。
# 关闭:与 Persister 同生命周期(entry point finally / SessionState.close)。
import json
import time
from dataclasses import asdict
from pathlib import Path

from .sink import EventSink
from .events import is_web_event, TextDelta
from ..persist.paths import events_path


class EventStore(EventSink):
    """把 web 契约事件逐条追加到 events.jsonl。同一 run 跨 turn append(与 Persister 同模式)。

    seq:单调自增(断点续传游标用)。初始化时从已有行数恢复(跨进程 append 保持单调),
    每条记录带 "seq",/stream 支持 Last-Event-ID 从游标后耐久补发。
    """

    def __init__(self, run_id: str, path: str | None = None):
        self.run_id = run_id
        self._path: Path = Path(path) if path else events_path(run_id)
        self._fh = None
        # 游标:从文件已有行数恢复(seq == 行号,单调递增;跨进程/重启续写不重置)
        self._seq = 0
        if self._path.exists():
            try:
                self._seq = sum(1 for _ in open(self._path, encoding="utf-8"))
            except OSError:
                self._seq = 0

    def emit(self, event) -> None:
        # delta 是瞬时流式(逐 token),不落盘——events.jsonl 保持消息级,
        # 恢复时用 AssistantMessage 的权威全文,不用 delta 重建(避免体积爆炸 + 重建失真)。
        if isinstance(event, TextDelta):
            return
        if not is_web_event(event):
            return
        if self._fh is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8")
        self._seq += 1
        rec = {"ts": time.time(), "seq": self._seq, "type": type(event).__name__}
        rec.update(asdict(event))
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()   # 低频追加写,sync flush 即可(同 Persister)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
