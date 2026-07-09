# AuditLogger：工具调用审计日志，记录 who/what/when/result，输出 JSONL。
#
# 对应面试题 17/18。用于合规追溯与安全审计（阶段 8 安全章复用）。
# log_path=None 时只内存收集（测试用）；有路径则追加写 JSONL（每行一条）。
#
# 不 import ToolCall：用 Any + 鸭子类型（call.call_id/tool_name/arguments），保持纯净无环。
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, TextIO


@dataclass
class AuditRecord:
    """
    审计记录实体，用于记录工具调用的完整执行信息。
    每个工具调用（无论成功或失败）都会生成一条审计记录，
    用于后续的监控、排障、成本分析或合规审计。
    """
    call_id: str
    user_id: str | None
    tool_name: str
    arguments: dict[str, Any]
    ts: float                         # 墙钟时间（审计要看真实时刻）
    ok: bool
    error_type: str | None
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "ts": self.ts,
            "ok": ok if (ok := self.ok) else False,  # 保证可序列化
            "error_type": self.error_type,
            "elapsed_ms": self.elapsed_ms,
        }


class AuditLogger:
    """工具调用审计日志，记录 who/what/when/result，输出 JSONL。"""
    def __init__(self, log_path: str | None = None):
        self.log_path = log_path
        self._fh: TextIO | None = None
        if log_path:
            self._fh = open(log_path, "a", encoding="utf-8")
        self.records: list[AuditRecord] = []   # 内存副本，测试可查

    def log_before(self, call, user_id: str | None) -> float:
        """记录调用开始（暂不落盘），返回 start_ts 供 log_after 算耗时。"""
        return time.perf_counter()

    def log_after(self, call, user_id: str | None, start_ts: float, *,
                  ok: bool, error_type: str | None) -> None:
        """记录调用结束：拼成 AuditRecord，内存留底 + 可选写 JSONL。"""
        elapsed = round((time.perf_counter() - start_ts) * 1000, 2)
        rec = AuditRecord(
            call_id=call.call_id,
            user_id=user_id,
            tool_name=call.tool_name,
            arguments=call.arguments,
            ts=time.time(),
            ok=ok,
            error_type=error_type,
            elapsed_ms=elapsed,
        )
        self.records.append(rec)
        if self._fh:
            self._fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            self._fh.flush()

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None
