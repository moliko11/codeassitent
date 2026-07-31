# tracing/span.py - Span 数据模型 + Trace(阶段9 任务1/2)
# trace = span 树(观测,有层级+耗时);transcript = 消息流(重放)。共享 run_id,互补。
from dataclasses import dataclass, field
from typing import Literal, Optional
import time
import uuid

SpanType = Literal["run", "step", "tool", "guardrail", "approval"]


@dataclass
class Span:
    """一个 trace span(run/step/tool/guardrail/approval)。
    parent_id 建层级:run=None, step=run_span_id, tool=step_span_id。"""
    span_id: str
    parent_id: Optional[str]
    type: SpanType
    name: str
    start: float
    end: Optional[float] = None
    attrs: dict = field(default_factory=dict)

    def finish(self, **attrs):
        self.end = time.perf_counter()
        self.attrs.update(attrs)

    def duration_ms(self) -> Optional[float]:
        if self.end is None:
            return None
        return round((self.end - self.start) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "type": self.type,
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "duration_ms": self.duration_ms(),
            "attrs": self.attrs,
        }


@dataclass
class Trace:
    """一次 run 的 span 集合。"""
    run_id: str
    spans: list[Span] = field(default_factory=list)

    def add(self, span: Span):
        self.spans.append(span)

    def to_tree(self) -> str:
        """按 parent_id 建树,缩进打印(调试/可读)。"""
        children: dict[Optional[str], list[Span]] = {}
        for s in self.spans:
            children.setdefault(s.parent_id, []).append(s)
        lines = [f"trace run={self.run_id} ({len(self.spans)} spans)"]

        def render(parent_id, depth):
            for s in children.get(parent_id, []):
                dur = f"{s.duration_ms()}ms" if s.duration_ms() is not None else "open"
                attrs = f" {s.attrs}" if s.attrs else ""
                lines.append(f"{'  ' * depth}{s.type} {s.name} [{dur}{attrs}]")
                render(s.span_id, depth + 1)

        render(None, 1)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "spans": [s.to_dict() for s in self.spans]}

    @classmethod
    def from_dict(cls, data: dict) -> "Trace":
        return cls(
            run_id=data["run_id"],
            spans=[Span(**s) for s in data.get("spans", [])],
        )
