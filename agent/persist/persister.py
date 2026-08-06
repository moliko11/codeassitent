# persister.py
import json, time, uuid
from .paths import transcript_path
from ..core.state import _ser   # 复用,_ser 已跳 raw

class Persister:
    """消息级事实落盘。完整消息 append 到 transcript.jsonl。
    和 streaming sink 独立:deltas->printer(临时);本类->transcript(真相)。"""
    def __init__(self, run_id: str, agent_id=None):
        """run_id: transcript.jsonl 的唯一标识;agent_id: 标记记录来源(子 agent 落主 transcript 时="subagent")"""
        self._run_id = run_id
        self.agent_id = agent_id   # None=主 agent;子 agent 落盘时设 "subagent"(web 据此区分展示)
        self._fh = open(transcript_path(run_id), "a", encoding="utf-8")

    def _append(self, rec: dict):
        rec = {"run_id": self._run_id, "ts": time.perf_counter(),
               "agent_id": self.agent_id, **rec}
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()   # 消息级写频低,sync flush 即可(CC 用批写是因高频)

    # ── 消息级事实(对应 CC 的 TranscriptMessage) ──
    def log_user(self, content: str):
        self._append({"type": "user", "uuid": str(uuid.uuid4()), "content": content})

    def log_assistant(self, model_response):
        self._append({"type": "assistant", "uuid": str(uuid.uuid4()),
                      "text": model_response.text,
                      "tool_calls": _ser(model_response.tool_calls)})  # _ser 跳 raw

    def log_tool_result(self, result):
        # 逐 result 增量落盘(同 CC runTools 循环 per-update recordTranscript)。
        # 不批量:批量会丢"已完成但 execute_many 未返回"的工具结果,resume 整批重跑 -> 非幂等工具重复执行(硬伤1)。
        self._append({"type": "tool_result", "uuid": str(uuid.uuid4()),
                      "result": _ser(result)})

    def log_run_end(self, status: str, error=None):
        self._append({"type": "run_end", "status": status, "error": error})

    # ── 将来 fileHistory 的快照元数据也走这里(同 CC:异构条目同文件) ──
    # def log_file_history_snapshot(self, step_id, snapshot): ...

    def close(self): self._fh.close()