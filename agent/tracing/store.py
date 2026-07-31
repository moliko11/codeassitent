# tracing/store.py - TraceStore:trace.jsonl 落盘 + 读回(阶段9 任务2/5)
# 复用 persist/runs/<run_id>/ 目录(和 transcript.jsonl 同 run_id 同目录)。
# trace 是观测用(可丢),transcript 是真相(durability-first)。崩了没 RunEnd -> trace 没写,可接受。
import json
from pathlib import Path

from ..persist.paths import trace_path
from .span import Span, Trace


class TraceStore:
    """trace.jsonl 落盘(每 span 一行 JSONL)。一次 run 一个 trace,RunEnd 时覆盖写。"""

    def __init__(self, run_id: str, path: str | None = None):
        self.run_id = run_id
        self._path: Path = Path(path) if path else trace_path(run_id)

    def write(self, trace: Trace) -> None:
        """整条 trace 写一次(RunEnd 时调)。每 span 一行 JSONL。"""
        with open(self._path, "w", encoding="utf-8") as f:
            for span in trace.spans:
                f.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")

    def load(self) -> Trace:
        """从 trace.jsonl 读回 trace(离线分析 / MetricsCollector 用)。"""
        spans = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                spans.append(Span(
                    span_id=d["span_id"], parent_id=d.get("parent_id"),
                    type=d["type"], name=d["name"],
                    start=d["start"], end=d.get("end"),
                    attrs=d.get("attrs", {}),
                ))
        return Trace(run_id=self.run_id, spans=spans)
