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


def trace_path(run_id: str) -> Path:
    """trace.jsonl 落盘(阶段9 TraceStore 用,和 transcript 同 run_id 同目录)。"""
    return run_dir(run_id) / "trace.jsonl"


def run_meta_path(run_id: str) -> Path:
    """run_meta.json 侧车(监控 M1 用):RunEnd 落盘摘要,列表 O(1) 读不 load trace(坑3)。
    和 transcript/trace 同 run_id 同目录。"""
    return run_dir(run_id) / "run_meta.json"


def tool_results_dir(run_id: str) -> Path:
    """工具结果落盘子目录(步3 ToolResultBudget 用)。不 mkdir,由调用方按需建。"""
    return run_dir(run_id) / "tool-results"

def memory_dir() -> Path:
    """长期记忆目录(步6 Memory 用,跨 run 共享,与 runs/ 平级)。会 mkdir。"""
    d = PERSIST_ROOT.parent / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d