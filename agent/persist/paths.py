from pathlib import Path
PERSIST_ROOT = Path("persist/runs")
MAX_TRANSCRIPT_READ_BYTES = 50 * 1024 * 1024   # 同 CC,防 OOM

def run_dir(run_id: str) -> Path:
    # 这个目录下的 transcript.jsonl 可能很大,不适合放在内存里,所以 transcript.jsonl 直接落盘,不落内存
    d = PERSIST_ROOT / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def transcript_path(run_id: str) -> Path:
    # transcript.jsonl 直接落盘,不落内存
    return run_dir(run_id) / "transcript.jsonl"