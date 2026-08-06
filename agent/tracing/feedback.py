# tracing/feedback.py - FeedbackStore:用户反馈 + A/B variant(阶段9 任务5,题16/17)
# 文件存储(persist/feedback.jsonl),不做 DB。A/B variant 简单字段(run.meta["variant"])。
import json
import time
from pathlib import Path
from ..persist.paths import PERSIST_ROOT


class FeedbackStore:
    """用户反馈存储:👍/👎 + 评论 + variant。文件追加 JSONL。

    A/B:run 用 variant 标识(如 "v1"/"v2"),反馈按 variant 聚合 👍率对比。
    """

    def __init__(self, path: str | None = None):
        # 默认 persist/feedback.jsonl(PERSIST_ROOT=persist/runs,parent=persist)
        self._path = Path(path) if path else PERSIST_ROOT.parent / "feedback.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, run_id: str, variant: str | None = None,
               rating: bool = True, comment: str = "") -> None:
        """记录一条反馈。rating=True=👍,False=👎。"""
        rec = {"run_id": run_id, "variant": variant, "rating": rating,
               "comment": comment, "ts": time.time()}
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def aggregate(self) -> dict:
        """按 variant 聚合 👍率。返回 {variant: {total, thumbs_up, thumbs_up_rate}}。"""
        stats: dict[str | None, dict] = {}
        if not self._path.exists():
            return stats
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                v = rec.get("variant")
                s = stats.setdefault(v, {"total": 0, "thumbs_up": 0})
                s["total"] += 1
                if rec.get("rating"):
                    s["thumbs_up"] += 1
        for s in stats.values():
            s["thumbs_up_rate"] = (s["thumbs_up"] / s["total"]) if s["total"] else 0.0
        return stats
