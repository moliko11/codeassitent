# chatweb/backend/file_history_api.py - 桌面 diff 视图 API(Phase 2 §2.5)
#
# 只读 file-history-meta.jsonl sidecar(session_manager.make_file_history 每步快照落盘)
# + file-history/{sha16}@v{version} 备份文件。复用 M1 数据层,不跑 agent loop。
#
# 路径安全:key = sha256(abs_path)[:16](与 FileHistory._backup_name 同款 hash)。所有读操作先经
# sidecar 反查 abs_path —— 只读 agent 历史合法写过的路径,不从用户输入构造 fs 路径,无穿越面。
# run 无 sidecar(功能落地前的旧 run)-> 空列表;run 目录不存在 -> 404。
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from agent.persist import paths as ppaths   # 动态读 PERSIST_ROOT(测试 monkeypatch 生效)

router = APIRouter()


def _key_of(abs_path: str) -> str:
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]


def _meta_path(run_id: str) -> Path:
    return ppaths.PERSIST_ROOT / run_id / "file-history-meta.jsonl"


def _load_index(run_id: str) -> Optional[dict]:
    """读 sidecar -> {key: {path, name, current_exists, versions:[{version, step_id, time, exists, backup}]}}。
    run 目录不存在 -> None(run 不存在,HTTP 404);无 sidecar -> {}。"""
    rdir = ppaths.PERSIST_ROOT / run_id
    if not rdir.is_dir():
        return None
    p = _meta_path(run_id)
    if not p.exists():
        return {}
    backup_dir = rdir / "file-history"
    index: dict[str, dict] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        step_id = d.get("step_id")
        ts = d.get("ts", 0.0)
        for abs_path, v in (d.get("tracked") or {}).items():
            key = _key_of(abs_path)
            entry = index.setdefault(key, {
                "path": abs_path,
                "name": os.path.basename(abs_path.replace("\\", "/")) or abs_path,
                "current_exists": Path(abs_path).exists(),
                "versions": [],
            })
            ver = v.get("version")
            backup_name = v.get("file")
            if any(x["version"] == ver for x in entry["versions"]):
                continue
            entry["versions"].append({
                "version": ver,
                "step_id": step_id,
                "time": v.get("time", 0.0),
                "exists": bool(backup_name) and (backup_dir / backup_name).exists(),
                "backup": backup_name,
            })
    for entry in index.values():
        entry["versions"].sort(key=lambda x: x["version"])
    return index


def _entry_to_payload(key: str, entry: dict) -> dict:
    """去掉内部 backup 字段(纯元数据,不把磁盘文件名暴露给前端)。"""
    return {
        "key": key,
        "path": entry["path"],
        "name": entry["name"],
        "current_exists": entry["current_exists"],
        "versions": [{k: v for k, v in x.items() if k != "backup"} for x in entry["versions"]],
    }


@router.get("/sessions/{run_id}/files")
def list_files(run_id: str):
    """该 run 编辑过的文件 + 版本链(喂前端 diff 面板左列)。旧 run(无 sidecar)-> []。"""
    index = _load_index(run_id)
    if index is None:
        raise HTTPException(404, "run not found")
    return [_entry_to_payload(k, v) for k, v in sorted(index.items())]


@router.get("/sessions/{run_id}/files/{key}/versions")
def file_versions(run_id: str, key: str):
    """单文件版本链(key = sha256(abs_path)[:16])。key 不在 sidecar -> 404。"""
    index = _load_index(run_id)
    if index is None:
        raise HTTPException(404, "run not found")
    entry = index.get(key)
    if entry is None:
        raise HTTPException(404, "file not found")
    return _entry_to_payload(key, entry)


@router.get("/sessions/{run_id}/files/{key}/content")
def file_content(run_id: str, key: str, version: str = Query("current")):
    """某版本内容:version=N 读 file-history/{sha16}@vN;缺省/current 读磁盘当前内容。
    null backup / 文件已删 -> exists:false, content:"";版本不存在 -> 404。"""
    index = _load_index(run_id)
    if index is None:
        raise HTTPException(404, "run not found")
    entry = index.get(key)
    if entry is None:
        raise HTTPException(404, "file not found")
    abs_path = entry["path"]

    def _payload(exists: bool, content: str, ver) -> dict:
        return {"key": key, "path": abs_path, "version": ver, "exists": exists, "content": content}

    def _read(path: Path, ver) -> dict:
        try:
            if path.exists():
                return _payload(True, path.read_text(encoding="utf-8", errors="replace"), ver)
            return _payload(False, "", ver)
        except OSError:
            return _payload(False, "", ver)

    if version in ("current", ""):
        return _read(Path(abs_path), "current")
    try:
        v = int(version)
    except ValueError:
        raise HTTPException(422, "version must be 'current' or an integer")
    for item in entry["versions"]:
        if item["version"] == v:
            backup = item.get("backup")
            if not backup:                    # null backup(该版本文件不存在)-> exists:false
                return _payload(False, "", v)
            return _read(ppaths.PERSIST_ROOT / run_id / "file-history" / backup, v)
    raise HTTPException(404, "version not found")
