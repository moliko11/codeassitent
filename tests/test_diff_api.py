"""桌面 diff 视图 API 验收测试(Phase 2 §2.5)。

覆盖 file-history sidecar + 3 端点:
- GET /sessions/{run_id}/files                    文件 + 版本链列表
- GET /sessions/{run_id}/files/{key}/versions     单文件版本链
- GET /sessions/{run_id}/files/{key}/content      版本内容(缺省=current 读磁盘)
+ FileHistory.make_snapshot(on_snapshot=...) 回调、make_file_history 从 sidecar 全量重建。

用 FastAPI TestClient,不启真 server。chatweb backend 模块级读 .env(缺 key 直接 raise),
所以 import 包 try/except + requires_server skip(和 test_web 只读 monitor 不同)。运行:
    python -m pytest tests/test_diff_api.py -v
"""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import agent.persist.paths as paths

try:
    from chatweb.backend.server import app
    _HAVE_SERVER = True
except Exception:
    _HAVE_SERVER = False

requires_server = pytest.mark.skipif(
    not _HAVE_SERVER, reason="chatweb backend 需 code/.env 配 API key(缺 key 模块级 raise)")

client = TestClient(app) if _HAVE_SERVER else None


def _sha16(p: str) -> str:
    return hashlib.sha256(p.encode("utf-8")).hexdigest()[:16]


def _seed_fh(run_id, tmp_path):
    """seed 一个 run 的 file-history sidecar + 备份文件 + 当前磁盘文件。

    main.py:有备份链(原版 v1 = return 1,编辑后 v2 = return 2,当前磁盘 = return 3)
    new.py :新建文件,两版都 null backup(该版本文件不存在)。
    返回 (main_abs, main_key, new_key)。
    """
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    fpath = repo / "main.py"
    fpath.write_text("def foo():\n    return 3\n", encoding="utf-8")
    npath = repo / "new.py"            # 新建文件:磁盘存在,但 v1/v2 都是 null backup
    npath.write_text("print('new')\n", encoding="utf-8")
    abs_main = str(fpath.resolve())
    abs_new = str(npath.resolve())
    key_main = _sha16(abs_main)
    key_new = _sha16(abs_new)

    rdir = paths.PERSIST_ROOT / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    bdir = rdir / "file-history"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / f"{key_main}@v1").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (bdir / f"{key_main}@v2").write_text("def foo():\n    return 2\n", encoding="utf-8")

    meta = [
        {"step_id": -1, "ts": 1.0, "tracked": {
            abs_main: {"file": f"{key_main}@v1", "version": 1, "time": 1.0},
            abs_new:  {"file": None, "version": 1, "time": 1.0},
        }},
        {"step_id": 0, "ts": 2.0, "tracked": {
            abs_main: {"file": f"{key_main}@v2", "version": 2, "time": 2.0},
            abs_new:  {"file": None, "version": 2, "time": 2.0},
        }},
    ]
    (rdir / "file-history-meta.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in meta) + "\n", encoding="utf-8")
    return abs_main, key_main, key_new


# ─────────────────── API ───────────────────

@requires_server
def test_files_list(tmp_path):
    """GET /sessions/{id}/files -> 文件 + 版本链,按 version 升序。"""
    abs_main, key_main, key_new = _seed_fh("r-fh", tmp_path)
    data = client.get("/sessions/r-fh/files").json()
    assert len(data) == 2
    by_key = {f["key"]: f for f in data}
    f = by_key[key_main]
    assert f["name"] == "main.py" and f["path"] == abs_main
    assert f["current_exists"] is True
    assert [v["version"] for v in f["versions"]] == [1, 2]
    assert all(v["exists"] for v in f["versions"])
    assert f["versions"][0]["step_id"] == -1          # 原版挂在初始快照
    assert "backup" not in f["versions"][0]            # 不暴露磁盘文件名


@requires_server
def test_file_versions(tmp_path):
    """GET /sessions/{id}/files/{key}/versions -> 单文件版本链。"""
    _, key_main, _ = _seed_fh("r-fh", tmp_path)
    d = client.get(f"/sessions/r-fh/files/{key_main}/versions").json()
    assert d["key"] == key_main
    assert len(d["versions"]) == 2
    assert d["versions"][0]["step_id"] == -1


@requires_server
def test_content_version(tmp_path):
    """GET .../content?version=2 -> 返回该版本备份内容。"""
    _, key_main, _ = _seed_fh("r-fh", tmp_path)
    r = client.get(f"/sessions/r-fh/files/{key_main}/content", params={"version": 2})
    assert r.status_code == 200
    d = r.json()
    assert d["version"] == 2 and d["exists"] is True and "return 2" in d["content"]


@requires_server
def test_content_current_default(tmp_path):
    """GET .../content 缺省 -> 读磁盘当前内容。"""
    _, key_main, _ = _seed_fh("r-fh", tmp_path)
    d = client.get(f"/sessions/r-fh/files/{key_main}/content").json()
    assert d["version"] == "current" and d["exists"] is True and "return 3" in d["content"]


@requires_server
def test_content_null_backup(tmp_path):
    """新建文件(null backup)-> exists:false, content:""(该版本文件当时不存在)。"""
    _, _, key_new = _seed_fh("r-fh", tmp_path)
    d = client.get(f"/sessions/r-fh/files/{key_new}/content", params={"version": 1}).json()
    assert d["exists"] is False and d["content"] == ""
    # current 仍可读磁盘(文件后来被创建了)
    d2 = client.get(f"/sessions/r-fh/files/{key_new}/content").json()
    assert d2["exists"] is True


@requires_server
def test_404s(tmp_path):
    """未知 key / 未知版本 / run 不存在 -> 404。"""
    _, key_main, _ = _seed_fh("r-fh", tmp_path)
    assert client.get("/sessions/r-fh/files/aaaaaaaaaaaaaaaa/versions").status_code == 404
    assert client.get(f"/sessions/r-fh/files/{key_main}/content",
                      params={"version": 99}).status_code == 404
    assert client.get("/sessions/nope/files").status_code == 404
    assert client.get("/sessions/nope/files/aaaaaaaaaaaaaaaa/versions").status_code == 404


@requires_server
def test_files_empty_when_no_sidecar(tmp_path):
    """旧 run(有目录无 sidecar)-> 空列表(不 404,前端空态)。"""
    (paths.PERSIST_ROOT / "r-old").mkdir(parents=True, exist_ok=True)
    assert client.get("/sessions/r-old/files").json() == []


# ─────────────────── 纯单元:on_snapshot 回调 + sidecar 重建 ───────────────────

def test_make_snapshot_fires_on_snapshot(tmp_path):
    """FileHistory(on_snapshot=...) 在 make_snapshot 后回调一次(Phase 2 §2.5 侧车钩子)。"""
    from agent.utils.fileHistory import FileHistory
    seen = []
    fh = FileHistory(tmp_path / "backups", on_snapshot=lambda snap: seen.append(snap.step_id))
    p = tmp_path / "a.py"
    p.write_text("v1", encoding="utf-8")
    fh.track_edit(str(p), step_id=0)
    fh.make_snapshot(0)
    assert seen == [0]


@requires_server
def test_make_file_history_restores_from_sidecar(tmp_path):
    """make_file_history 从 sidecar 全量重建(进程重启 / resume 旧 run 版本连续)。"""
    from chatweb.backend.session_manager import make_file_history
    abs_main, _, _ = _seed_fh("r-fh", tmp_path)
    fh = make_file_history("r-fh")
    assert len(fh.snapshots) == 2                       # 2 条快照全还原
    assert abs_main in fh.tracked_files
    # 新快照继续走 sidecar(append,不重写旧行)
    import io
    lines_before = (paths.PERSIST_ROOT / "r-fh" / "file-history-meta.jsonl").read_text(
        encoding="utf-8").count("\n")
    p = tmp_path / "repo" / "b.py"
    p.write_text("x", encoding="utf-8")
    fh.track_edit(str(p), step_id=1)
    fh.make_snapshot(1)
    lines_after = (paths.PERSIST_ROOT / "r-fh" / "file-history-meta.jsonl").read_text(
        encoding="utf-8").count("\n")
    assert lines_after == lines_before + 1              # 只追加新快照一行
