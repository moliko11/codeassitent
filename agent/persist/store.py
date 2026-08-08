# persist/store.py
import json
import logging

from .paths import transcript_path, MAX_TRANSCRIPT_READ_BYTES

_log = logging.getLogger(__name__)


def read_transcript(run_id: str):
    """逐行读 transcript.jsonl，yield dict。

    容错（硬伤 4.2）：json 语法错行跳过+告警；schema 错留给 apply_message 再 try/except。
    体积（硬伤 4.3）：超 MAX_TRANSCRIPT_READ_BYTES 报错（阶段 5 先报错，compaction 后加）。
    """
    p = transcript_path(run_id)
    if not p.exists():
        return                       # generator 里的 return = 空生成
    size = p.stat().st_size
    if size > MAX_TRANSCRIPT_READ_BYTES:
        raise RuntimeError(f"transcript too large ({size}B)，需 compaction")
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                _log.warning("read_transcript: 跳过损坏行 (run_id=%s)", run_id)


def read_events(run_id: str) -> list[dict] | None:
    """读 events.jsonl(前端事件流)供前端重放,恢复画面 = 直播画面。

    无 events.jsonl(老 run,只有 transcript)返回 None,调用方退回落 transcript;
    损坏行跳过+告警(同 read_transcript)。返回的事件列表每条含 type/字段/ts,
    前端可直接过 eventReducer 重放(不需要第二套恢复逻辑)。
    """
    from . import paths
    p = paths.PERSIST_ROOT / run_id / "events.jsonl"   # 直构,避免 run_dir 的 mkdir 副作用(同 read_run_report)
    if not p.exists():
        return None
    out: list[dict] = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                _log.warning("read_events: 跳过损坏行 (run_id=%s)", run_id)
    return out


# ── 监控 M1:读 run(列表/单 run 指标),只读不改采集层 ──

def _scan_transcript_tail(run_id: str) -> dict:
    """退化:无 run_meta 侧车时扫 transcript 拿 status(坑2:崩了没 RunEnd -> 无 trace 无侧车)。
    只能拿 status(token 在 trace 的 step span usage 里,transcript 没有 -> 一律 0)。
    无 run_end 行 = 在跑/崩在 RunEnd 前 -> status='running'。read_transcript 报错 -> 'unknown'。
    Phase 1 §1.1:顺带扫首条真实 user 消息作 title(无侧车时的标题兜底)。"""
    meta = {
        "run_id": run_id, "status": "running",
        "title": "",
        "started_at": 0, "ended_at": 0, "duration_ms": 0.0,
        "token_input": 0, "token_output": 0, "token_total": 0,
        "step_count": 0, "tool_count": 0, "tool_success_rate": 0.0,
        "model": "unknown",
    }
    try:
        last_end = None
        for rec in read_transcript(run_id):
            rtype = rec.get("type")
            if rtype == "run_end":
                last_end = rec
            elif rtype == "user" and not meta["title"]:
                content = rec.get("content")
                if isinstance(content, str) and content.strip():
                    # 跳过系统注入的合成 user 消息(与 agentloop._first_user_title 一致)
                    text = content.strip()
                    if text.startswith(("[plan step", "[task-notification", "[子任务", "[系统提示")):
                        continue
                    meta["title"] = text[:30] + "…" if len(text) > 30 else text
    except RuntimeError:
        meta["status"] = "unknown"   # transcript 过大等,读不动
        return meta
    if last_end is not None:
        meta["status"] = last_end.get("status", "unknown")
        meta["ended_at"] = last_end.get("ts", 0)   # perf_counter(非墙钟),退化只能给这个
    return meta


def set_run_title(run_id: str, title: str) -> None:
    """更新 run_meta.json 的 title(Phase 1 §1.1,前端重命名会话)。无侧车则 no-op
    (没 RunEnd 的 run 本来也列不出来标题;重命名只对已落盘的 run 有意义)。"""
    if not title:
        return
    from .paths import PERSIST_ROOT
    meta_p = PERSIST_ROOT / run_id / "run_meta.json"
    if not meta_p.exists():
        return
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    meta["title"] = title
    try:
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def list_runs() -> list[dict]:
    """列出所有 run 的摘要(按 started_at 倒序)。列表性能关键(坑3):优先读 run_meta.json 侧车
    (O(1)),没侧车的 run 退化扫 transcript 末尾 run_end 行(坑2)。不逐个 load trace。
    PERSIST_ROOT 是相对路径(坑6),必须在 code/ 下调用。"""
    from . import paths
    out = []
    root = paths.PERSIST_ROOT
    if not root.exists():
        return out
    for d in root.iterdir():
        if not d.is_dir():
            continue
        run_id = d.name
        meta_p = d / "run_meta.json"          # 直构路径,不走 run_dir(避免读操作 mkdir)
        if meta_p.exists():
            try:
                out.append(json.loads(meta_p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                out.append(_scan_transcript_tail(run_id))
        else:
            out.append(_scan_transcript_tail(run_id))
    out.sort(key=lambda r: r.get("started_at", 0), reverse=True)
    return out


def read_run_report(run_id: str):
    """单 run 指标:load trace -> MetricsCollector.collect。
    trace.jsonl 不存在(崩了没 RunEnd,坑2)返回 None。token = step span usage 之和(坑1:精确值)。"""
    from ..tracing.store import TraceStore
    from ..tracing.metrics import MetricsCollector
    from . import paths
    tp = paths.PERSIST_ROOT / run_id / "trace.jsonl"   # 直构,避免 run_dir 的 mkdir 副作用
    if not tp.exists():
        return None
    trace = TraceStore(run_id, path=str(tp)).load()
    return MetricsCollector().collect(trace)