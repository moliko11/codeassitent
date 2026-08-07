# web/server.py - 监控后台 FastAPI server(M2 API + M3 单页 UI)
#
# 只读监控:复用 M1 数据层(list_runs/read_run_report/aggregate_stats/TraceStore/read_transcript),
# 不跑 agent loop、不碰 async 桥接(那是 chat UI Phase A 的事,见 web-layer-plan)。
# 端点全同步 def(纯读文件),FastAPI 自动丢线程池,TestClient 也能直跑。
#
# 必须从 code/ 启动(PERSIST_ROOT 相对路径,坑6;与 REPL 同约束)。
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from agent.persist import paths as ppaths          # 动态读 PERSIST_ROOT(测试 monkeypatch 生效)
from agent.persist import list_runs, read_run_report, read_transcript
from agent.persist.store import _scan_transcript_tail
from agent.tracing.store import TraceStore
from agent.tracing.aggregate import aggregate_stats
from agent.tracing.feedback import FeedbackStore
from agent.config.config import AgentConfig

app = FastAPI(title="ez-interview 监控后台")
_TEMPLATES = Path(__file__).parent / "templates"


def _split_sections(text: str) -> dict:
    """把系统提示词按 ## 标题分层:返回 {intro, sections:[{title,body}]}。
    首段(首个 ## 之前)作 intro;每个 `## 标题` 起一段。"""
    intro: list[str] = []
    sections: list[dict] = []
    cur: dict | None = None
    for line in text.split("\n"):
        if line.startswith("## "):
            if cur is not None:
                sections.append(cur)
            cur = {"title": line[3:].strip(), "body": []}
        elif cur is None:
            intro.append(line)
        else:
            cur["body"].append(line)
    if cur is not None:
        sections.append(cur)
    return {
        "intro": "\n".join(intro).strip(),
        "sections": [{"title": s["title"], "body": "\n".join(s["body"]).strip()} for s in sections],
    }


def _read_run_meta(run_id: str) -> dict | None:
    """单个 run 的 meta:优先 run_meta.json 侧车(O(1)),无则退化扫 transcript(坑2)。
    run 目录不存在 -> None。"""
    rdir = ppaths.PERSIST_ROOT / run_id
    if not rdir.is_dir():
        return None
    meta_p = rdir / "run_meta.json"
    if meta_p.exists():
        try:
            return json.loads(meta_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _scan_transcript_tail(run_id)   # 退化:扫 transcript 末尾 run_end 拿 status(token=0)


# ── M3 UI:迁移到 React 前端(code/monitor/frontend),旧 dashboard.html 保留在 templates/ 备用 ──

@app.get("/")
def root():
    """迁移到 React 前端后:重定向到前端 dev server(:5173)。
    生产可由反向代理或挂载 frontend/dist 静态文件接管。"""
    return RedirectResponse(url="http://localhost:5173")


# ── M2 API ──

@app.get("/api/stats")
def api_stats():
    """跨 run 聚合(总 token / run 数 / 平均成功率 / by_day / by_model)。"""
    return aggregate_stats(list_runs()).to_dict()


@app.get("/api/runs")
def api_runs():
    """会话列表(run_meta 摘要,按 started_at 倒序)。"""
    return list_runs()


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    """单 run 详情:meta(侧车或退化)+ report(load trace 聚合,无 trace 则 None)。"""
    meta = _read_run_meta(run_id)
    if meta is None:
        raise HTTPException(404, "run not found")
    report = read_run_report(run_id)   # trace 不存在返 None(坑2)
    return {"meta": meta, "report": report.to_dict() if report else None}


@app.get("/api/runs/{run_id}/trace")
def api_run_trace(run_id: str):
    """span 树 JSON(前端画火焰图)。trace.jsonl 不存在(崩了没 RunEnd,坑2)-> 404。"""
    tp = ppaths.PERSIST_ROOT / run_id / "trace.jsonl"   # 直构,避免 run_dir 的 mkdir 副作用
    if not tp.exists():
        raise HTTPException(404, "trace not found (run 崩了没 RunEnd,坑2)")
    trace = TraceStore(run_id, path=str(tp)).load()
    return trace.to_dict()


@app.get("/api/runs/{run_id}/transcript")
def api_run_transcript(run_id: str, limit: int = Query(100000, ge=1, le=100000)):
    """消息流(全量;OOM 由 read_transcript 的 50MB 上限兜底)。limit 保留但默认极大=返回全部。"""
    try:
        recs = list(read_transcript(run_id))
    except RuntimeError as e:   # transcript 过大(>50MB)
        raise HTTPException(413, str(e))
    return recs[-limit:]


@app.get("/api/feedback")
def api_feedback():
    """反馈按 variant 聚合(👍率)。"""
    return FeedbackStore().aggregate()


@app.get("/api/system_prompt")
def api_system_prompt():
    """首轮加载的系统提示词,按 ## 标题分层(intro + sections + raw)。
    源:AgentConfig().system_prompt(REPL 用默认配置,main 不覆盖即 DEFAULT_SYSTEM_PROMPT)。"""
    prompt = AgentConfig().system_prompt
    d = _split_sections(prompt)
    d["raw"] = prompt
    return d


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
