# web/server.py - 监控后台 FastAPI server(M2 API + M3 单页 UI)
#
# 只读监控:复用 M1 数据层(list_runs/read_run_report/aggregate_stats/TraceStore/read_transcript),
# 不跑 agent loop、不碰 async 桥接(那是 chat UI Phase A 的事,见 web-layer-plan)。
# 端点全同步 def(纯读文件),FastAPI 自动丢线程池,TestClient 也能直跑。
#
# 必须从 code/ 启动(PERSIST_ROOT 相对路径,坑6;与 REPL 同约束)。
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

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


def _system_prompt_override_path() -> Path:
    """会话级系统提示词覆写文件(persist 同级 system_prompt.md)。存在则优先于默认静态版。
    Phase 3 §3.3:管理页编辑保存到这里,GET 读它。删掉 = 恢复默认。"""
    return ppaths.PERSIST_ROOT.parent / "system_prompt.md"


def _read_system_prompt() -> str:
    """当前生效的系统提示词:有覆写文件读覆写,否则 AgentConfig 默认。"""
    p = _system_prompt_override_path()
    if p.exists():
        try:
            txt = p.read_text(encoding="utf-8")
            if txt.strip():
                return txt
        except OSError:
            pass
    return AgentConfig().system_prompt


def _system_prompt_source() -> str:
    """当前生效来源:"override"(persist/system_prompt.md 非空)或 "default"。"""
    p = _system_prompt_override_path()
    if p.exists():
        try:
            if p.read_text(encoding="utf-8").strip():
                return "override"
        except OSError:
            pass
    return "default"


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


def _collapse_run_roots(spans: list) -> list:
    """同名 run 根折叠:多轮同名 run span(parent=null 多个)合成一个根(一个对话一棵树)。

    Tracer 已修"一个会话只建一个 run span";此处兜底旧 trace.jsonl(每轮一个同名 run span):
    保留第一个 run 作根,其余 run 的直接子(step)改挂到根下,丢弃多余 run span。
    只改返回前的内存对象(TraceStore.load 每请求新读),不改落盘数据。
    """
    runs = [s for s in spans if s.type == "run" and s.parent_id is None]
    if len(runs) <= 1:
        return spans
    keep = runs[0]
    drop_ids = {r.span_id for r in runs[1:]}
    # 合并根覆盖整个对话:start 取最早轮次,end 取最晚已结束轮次(旧数据每轮 run 只有自己时长)
    ends = [r.end for r in runs if r.end is not None]
    keep.start = min(r.start for r in runs)
    if ends:
        keep.end = max(ends)
    for s in spans:
        if s.parent_id in drop_ids:
            s.parent_id = keep.span_id   # 重挂被折叠 run 的直接子(step)到根
    return [s for s in spans if s.span_id not in drop_ids]


@app.get("/api/runs/{run_id}/trace")
def api_run_trace(run_id: str):
    """span 树 JSON(前端画火焰图)。trace.jsonl 不存在(崩了没 RunEnd,坑2)-> 404。
    _collapse_run_roots:旧数据多轮同名 run span 堆叠,返回前折叠成一个根。"""
    tp = ppaths.PERSIST_ROOT / run_id / "trace.jsonl"   # 直构,避免 run_dir 的 mkdir 副作用
    if not tp.exists():
        raise HTTPException(404, "trace not found (run 崩了没 RunEnd,坑2)")
    trace = TraceStore(run_id, path=str(tp)).load()
    trace.spans = _collapse_run_roots(trace.spans)
    return trace.to_dict()


@app.get("/api/runs/{run_id}/transcript")
def api_run_transcript(run_id: str, limit: int = Query(100000, ge=1, le=100000)):
    """消息流(全量;OOM 由 read_transcript 的 50MB 上限兜底)。limit 保留但默认极大=返回全部。"""
    try:
        recs = list(read_transcript(run_id))
    except RuntimeError as e:   # transcript 过大(>50MB)
        raise HTTPException(413, str(e))
    return recs[-limit:]


@app.get("/api/runs/{run_id}/subagents")
def api_run_subagents(run_id: str):
    """Phase 3 §3.2:子 agent 活动列表(transcript 里 agent_id="subagent" 的记录聚合)。
    无子 agent 活动返回空列表(不 404,UI 显示空态)。"""
    if not (ppaths.PERSIST_ROOT / run_id).is_dir():
        raise HTTPException(404, "run not found")
    return aggregate_subagents(run_id)


@app.get("/api/stats/tools")
def api_stats_tools():
    """Phase 3 §3.5:工具使用统计(逐 run load trace 聚合 tool span)。"""
    return aggregate_tools()


@app.get("/api/feedback")
def api_feedback():
    """反馈按 variant 聚合(👍率)。"""
    return FeedbackStore().aggregate()


class SystemPromptBody(BaseModel):
    raw: str


@app.get("/api/system_prompt")
def api_system_prompt():
    """当前生效的系统提示词,按 ## 标题分层(intro + sections + raw + source)。
    Phase 3 §3.3:有覆写文件读覆写(会话级覆盖),否则 AgentConfig 默认(静态 DEFAULT_SYSTEM_PROMPT)。
    source="override"|"default" 供前端标来源徽标。"""
    prompt = _read_system_prompt()
    d = _split_sections(prompt)
    d["raw"] = prompt
    d["source"] = _system_prompt_source()
    return d


@app.post("/api/system_prompt")
def api_system_prompt_save(body: SystemPromptBody):
    """Phase 3 §3.3:保存系统提示词覆写(写 persist/system_prompt.md)。下次 GET/加载生效。"""
    p = _system_prompt_override_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.raw or "", encoding="utf-8")
    return {"ok": True, "saved_to": str(p), "chars": len(body.raw or "")}


@app.delete("/api/system_prompt")
def api_system_prompt_reset():
    """Phase 3 §3.3:删除覆写文件,恢复默认提示词。"""
    p = _system_prompt_override_path()
    existed = p.exists()
    if existed:
        try:
            p.unlink()
        except OSError:
            raise HTTPException(500, "删除覆写文件失败")
    return {"ok": True, "reset": existed}


# ── Phase 3 §3.2:子 agent 活动聚合(transcript 里 agent_id="subagent" 的记录按连续段分组)──

def aggregate_subagents(run_id: str) -> list[dict]:
    """子 agent 活动列表:主 agent 用 Task 工具派子 agent 时,子 agent 的事件带
    agent_id="subagent" 落主 transcript。按「连续段」分组(主 agent 的非 subagent 记录作分隔),
    每段聚合成一条活动:步骤数/工具/成功率/token/最终输出。"""
    recs = list(read_transcript(run_id))
    groups: list[dict] = []
    cur: dict | None = None
    for rec in recs:
        if rec.get("agent_id") == "subagent":
            if cur is None:
                cur = {"start_ts": rec.get("ts", 0), "records": []}
            cur["records"].append(rec)
            cur["end_ts"] = rec.get("ts", 0)
        else:
            if cur is not None:
                groups.append(cur)
                cur = None
    if cur is not None:
        groups.append(cur)

    out: list[dict] = []
    for i, g in enumerate(groups):
        tool_calls: list[dict] = []
        ok = tokens = step_count = 0
        output = ""
        for rec in g["records"]:
            t = rec.get("type")
            if t == "assistant":
                step_count += 1
                u = rec.get("usage") or {}
                tokens += (u.get("total_tokens", 0) or 0)
                if rec.get("text"):
                    output = rec["text"]                       # 最后一段 assistant 文本 = 最终输出
            elif t == "tool_result":
                res = rec.get("result") or {}
                tool_calls.append({"tool_name": res.get("tool_name"),
                                   "ok": bool(res.get("ok"))})
                if res.get("ok"):
                    ok += 1
        out.append({
            "id": i,
            "start_ts": g["start_ts"],
            "end_ts": g["end_ts"],
            "duration_ms": (g["end_ts"] - g["start_ts"]) * 1000,   # perf_counter 差(相对,非墙钟)
            "step_count": step_count,
            "tool_count": len(tool_calls),
            "tool_success_count": ok,
            "tool_success_rate": (ok / len(tool_calls)) if tool_calls else 0.0,
            "token_total": tokens,
            "output": output or None,
            "tool_calls": tool_calls,
        })
    return out


# ── Phase 3 §3.5:工具使用统计(逐 run load trace,聚合 tool span)──

def aggregate_tools() -> list[dict]:
    """按工具名聚合调用:次数/成功率/平均耗时/平均 attempts/重试/超时/错误分类。
    列表页不做(慢,aggregate.py 注释),这是独立 M2 端点,逐 run load trace 可接受。"""
    from agent.tracing.store import TraceStore
    agg: dict[str, dict] = {}
    for run in list_runs():
        run_id = run["run_id"]
        tp = ppaths.PERSIST_ROOT / run_id / "trace.jsonl"
        if not tp.exists():                       # 崩了没 RunEnd,坑2
            continue
        try:
            trace = TraceStore(run_id, path=str(tp)).load()
        except Exception:
            continue
        for span in trace.spans:
            if span.type != "tool":
                continue
            name = span.name or "unknown"
            a = agg.setdefault(name, {
                "tool": name, "call_count": 0, "success_count": 0,
                "total_elapsed_ms": 0.0, "attempts_total": 0,
                "timeout_count": 0, "error_types": {},
            })
            a["call_count"] += 1
            if span.attrs.get("ok"):
                a["success_count"] += 1
            d = span.duration_ms()
            if d is not None:
                a["total_elapsed_ms"] += d
            a["attempts_total"] += (span.attrs.get("attempts", 1) or 1)
            et = span.attrs.get("error_type")
            if et:
                a["error_types"][et] = a["error_types"].get(et, 0) + 1
                if "Timeout" in str(et):
                    a["timeout_count"] += 1
    out = []
    for a in agg.values():
        n = a["call_count"]
        a["success_rate"] = (a["success_count"] / n) if n else 0.0
        a["avg_elapsed_ms"] = (a["total_elapsed_ms"] / n) if n else 0.0
        a["avg_attempts"] = (a["attempts_total"] / n) if n else 0.0
        a["retry_count"] = a["attempts_total"] - n      # attempts>1 多出的执行次数
        out.append(a)
    out.sort(key=lambda a: a["call_count"], reverse=True)
    return out


if __name__ == "__main__":
    import uvicorn
    # 8000 留给 chatweb 后端,monitor 默认 8002;被占可用 MONITOR_PORT 覆盖(对齐 chatweb 的 AGENT_PORT)。
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MONITOR_PORT", "8002")))
