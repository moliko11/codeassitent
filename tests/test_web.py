"""监控后台 M2(API)验收测试。对齐 monitor-dashboard-plan §9 M2:
- GET /api/runs 返回列表 JSON
- GET /api/stats 返回聚合 JSON
- GET /api/runs/{id}/trace 返回 span 树 JSON
+ /api/runs/{id} report、/ HTML、404。

用 FastAPI TestClient(httpx,已装),不启真 server。直接落盘 run_meta.json + trace.jsonl
(隔离测 web 读层,不依赖 agentloop/真实 LLM)。运行(从 code/,3.12 venv):
    python -m pytest tests/test_web.py -v
"""
import json

import pytest
from fastapi.testclient import TestClient

import agent.persist.paths as paths

# app 在模块顶层导入(不捕获 PERSIST_ROOT;端点调用时才动态读,fixture 的 monkeypatch 生效)
from monitor.backend.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _tmp_persist_root(tmp_path, monkeypatch):
    """PERSIST_ROOT 指到 tmp_path,测试落盘不污染 code/persist(同 test_persist)。"""
    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")


def _seed_run(run_id, *, status="completed", model="deepseek-v4-pro",
              usage=None, started_at=1785655927.0):
    """落一个 run:run_meta.json 侧车 + trace.jsonl(run span + step span 带 usage)。"""
    usage = usage or {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "cached_tokens": 80}
    rdir = paths.PERSIST_ROOT / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": run_id, "status": status, "started_at": started_at,
        "ended_at": started_at + 1, "duration_ms": 1000.0,
        "token_input": usage["input_tokens"], "token_output": usage["output_tokens"],
        "token_total": usage["total_tokens"], "token_cached": usage.get("cached_tokens", 0),
        "step_count": 1, "tool_count": 0,
        "tool_success_rate": 0.0, "model": model,
        "system_prompt": "## 测试段\n测试内容(对齐 demo)",
    }
    (rdir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    spans = [
        {"span_id": "s0", "parent_id": None, "type": "run", "name": run_id,
         "start": 0.0, "end": 1.0, "duration_ms": 1000.0, "attrs": {"status": status}},
        {"span_id": "s1", "parent_id": "s0", "type": "step", "name": "0",
         "start": 0.1, "end": 0.9, "duration_ms": 800.0, "attrs": {"usage": usage}},
    ]
    with open(rdir / "trace.jsonl", "w", encoding="utf-8") as f:
        for s in spans:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return meta


def _seed_transcript_only(run_id, status="failed"):
    """只有 transcript(无 run_meta 无 trace),测退化 + 404(坑2)。"""
    from agent.persist import Persister
    from agent.core.models import ModelResponse
    p = Persister(run_id)
    p.log_user("hi")
    p.log_assistant(ModelResponse(text="boom"))
    p.log_run_end(status, None)
    p.close()


# ───────────────────────── API ─────────────────────────

def test_api_runs():
    """GET /api/runs -> 列表,含 token(读侧车)。"""
    _seed_run("r-1", usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
    _seed_run("r-2", model="qwen", usage={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10})
    r = client.get("/api/runs")
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 2
    by_id = {x["run_id"]: x for x in runs}
    assert by_id["r-1"]["token_total"] == 150
    assert by_id["r-2"]["model"] == "qwen"


def test_api_stats():
    """GET /api/stats -> 跨 run 聚合。"""
    _seed_run("r-1", usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150})
    _seed_run("r-2", model="qwen", usage={"input_tokens": 5, "output_tokens": 5, "total_tokens": 10})
    s = client.get("/api/stats").json()
    assert s["run_count"] == 2
    assert s["total_token"] == 160
    assert s["by_model"]["deepseek-v4-pro"]["token"] == 150
    assert s["by_model"]["qwen"]["token"] == 10


def test_api_run_detail():
    """GET /api/runs/{id} -> meta + report;report.token_total = step usage 之和(坑1)。"""
    _seed_run("r-1", usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "cached_tokens": 80})
    d = client.get("/api/runs/r-1").json()
    assert d["meta"]["status"] == "completed"
    assert d["meta"]["token_total"] == 150
    assert d["report"] is not None
    assert d["report"]["token_total"] == 150      # load trace 聚合,与侧车一致
    assert d["report"]["step_count"] == 1
    assert "## 测试段" in d["meta"]["system_prompt"]   # 按会话存的系统提示词
    assert d["meta"]["token_cached"] == 80              # 缓存命中 token


def test_api_run_trace():
    """GET /api/runs/{id}/trace -> span 树 JSON(前端画火焰图),含 step usage。"""
    _seed_run("r-1")
    t = client.get("/api/runs/r-1/trace").json()
    assert t["run_id"] == "r-1"
    assert len(t["spans"]) == 2
    step = next(s for s in t["spans"] if s["type"] == "step")
    assert step["attrs"]["usage"]["total_tokens"] == 150
    assert t["spans"][0]["type"] == "run" and t["spans"][0]["parent_id"] is None


def test_api_run_detail_fallback_no_trace():
    """run 有 transcript 无 trace(坑2)-> report=None,meta 走退化扫 transcript(status 对,token=0)。"""
    _seed_transcript_only("r-fail", status="failed")
    d = client.get("/api/runs/r-fail").json()
    assert d["report"] is None                     # 无 trace
    assert d["meta"]["status"] == "failed"         # 退化扫 run_end
    assert d["meta"]["token_total"] == 0           # transcript 无 usage


def test_trace_404_when_no_trace():
    """GET /api/runs/{id}/trace 无 trace.jsonl -> 404(坑2)。"""
    _seed_transcript_only("r-fail")
    r = client.get("/api/runs/r-fail/trace")
    assert r.status_code == 404


def test_run_404_when_not_exist():
    """GET /api/runs/{id} run 目录不存在 -> 404。"""
    assert client.get("/api/runs/never-existed").status_code == 404
    assert client.get("/api/runs/never-existed/trace").status_code == 404


def test_transcript_endpoint():
    """GET /api/runs/{id}/transcript -> 末尾消息列表。"""
    _seed_transcript_only("r-t", status="completed")
    recs = client.get("/api/runs/r-t/transcript").json()
    assert [r["type"] for r in recs] == ["user", "assistant", "run_end"]


# ───────────────────────── UI ─────────────────────────

def test_index_html():
    """GET / -> 307 重定向到 React 前端 dev server(:5173)。

    监控后台 React 化后(M3),后端 `/` 改为重定向到 Vite dev server;
    旧 dashboard.html 保留在 templates/ 备用,生产由反向代理或挂载 frontend/dist 接管。
    不再断言返回 HTML(React 迁移前的老行为)。
    """
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "http://localhost:5173"


def test_api_system_prompt():
    """GET /api/system_prompt -> 按 ## 标题分层(intro + sections + raw)。"""
    d = client.get("/api/system_prompt").json()
    assert d["intro"]                                    # 引言非空
    assert len(d["sections"]) >= 8                       # 至少 8 个 ## 段(实际 9)
    titles = [s["title"] for s in d["sections"]]
    assert any("终止约定" in t for t in titles)
    assert any("工具使用原则" in t for t in titles)
    assert any("记忆系统" in t for t in titles)
    assert d["raw"] and "## " in d["raw"]               # 原文含 ## 标记
    # 段体非空
    assert all(s["body"] for s in d["sections"])
