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