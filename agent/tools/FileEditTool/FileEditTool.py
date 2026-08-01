"""Edit 工具:精确字符串替换。三道闸门(对标 CC FileEditTool.ts):
1. 先读后改:read_file_state 无记录 -> 拒绝(对标 :275-287,errorCode 6)。
2. 陈旧检测:mtime 变了且内容变了 -> 拒绝重读(对标 :290-311,errorCode 7);
   mtime 变了内容没变(Windows 云同步)-> 不拒绝(兜底,对标 :296-310)。
3. trackEdit 备份:经 ToolExecutor.before_mutation 钩子(commit 4 接线),handler 内不调。
"""
from pathlib import Path

from ..registry import tool
from .. import _runtime_state

EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "文件路径"},
        "old_string": {"type": "string", "description": "要替换的字符串(须唯一,或 replace_all=True)"},
        "new_string": {"type": "string", "description": "替换为的字符串"},
        "replace_all": {"type": "boolean", "description": "默认 False;True 则全量替换所有匹配"},
    },
    "required": ["file_path", "old_string", "new_string"],
}


@tool(
    name="edit",
    description="精确字符串替换。改文件前必须先 Read。old_string 须唯一(否则用 replace_all=True)。",
    input_schema=EDIT_SCHEMA,
    mutates_external=True,   # 走 before_mutation -> trackEdit 备份
)
def edit(file_path, old_string, new_string, replace_all=False):
    ws = _runtime_state.workspace.get()
    path = ws.resolve(file_path) if ws else Path(file_path).resolve()
    if ws and not ws.allows(file_path):
        raise PermissionError(f"路径不在工作空间允许集内: {file_path}")
    abs_path = str(path)
    # 闸门 1:先读后改(对标 FileEditTool.ts:275-287)
    rec = _runtime_state.read_file_state.get(abs_path)
    if rec is None:
        raise ValueError("File has not been read yet. Read it first.")
    if rec.is_partial:
        raise ValueError("File was read partially. Read the full file first.")
    # 闸门 2:陈旧检测(对标 :290-311)。mtime 变 + 内容变 -> 拒绝;mtime 变内容没变 -> 不拒绝。
    if path.exists():
        cur_mtime = path.stat().st_mtime
        if cur_mtime > rec.mtime and path.read_text(encoding="utf-8") != rec.content:
            raise ValueError("File modified since read. Read it again.")
    # 闸门 3:trackEdit 备份由 before_mutation 钩子在 handler 前调(commit 4 接线),此处不调。
    # 替换
    content = path.read_text(encoding="utf-8")
    if old_string not in content:
        raise ValueError("String not found.")
    count = content.count(old_string)
    if count > 1 and not replace_all:
        raise ValueError(f"Found {count} matches, need more context or replace_all=True.")
    new_content = content.replace(old_string, new_string) if replace_all \
        else content.replace(old_string, new_string, 1)
    path.write_text(new_content, encoding="utf-8")
    # 更新 read_file_state(改后内容 + 新 mtime,后续 Edit 不需重读)
    _runtime_state.read_file_state[abs_path] = _runtime_state.ReadRecord(
        content=new_content, mtime=path.stat().st_mtime, is_partial=False)
    return f"Edited {file_path} ({count} replacement{'s' if count > 1 else ''})"
