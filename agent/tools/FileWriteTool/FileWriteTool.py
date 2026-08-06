"""Write 工具:创建新文件或全量重写(对标 CC FileWriteTool)。

- 覆盖已有非空文件需先 Read(防盲改);空文件视同新建(不需先 Read)。
- 改前 trackEdit 备份经 before_mutation 钩子(commit 4 接线)。
- prompt 约定:改已有文件用 Edit(发 diff),Write 只用于新建/全量重写。
"""
from pathlib import Path

from ..registry import tool
from .. import _runtime_state

WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "文件全文内容"},
    },
    "required": ["file_path", "content"],
}


@tool(
    name="write",
    description="创建新文件或全量重写。覆盖已有非空文件需先 Read。父目录不存在自动建。",
    input_schema=WRITE_SCHEMA,
    mutates_external=True,   # 走 before_mutation -> trackEdit 备份
)
def write(file_path, content):
    ws = _runtime_state.workspace.get()
    path = ws.resolve(file_path) if ws else Path(file_path).resolve()
    if ws and not ws.allows(file_path):
        raise PermissionError(f"路径不在工作空间允许集内: {file_path}")
    abs_path = str(path)
    # 覆盖已有非空文件需先 Read;空文件视同新建(对标 CC:空文件不算"已有内容")。
    if path.exists() and path.stat().st_size > 0:
        rec = _runtime_state.read_file_state.get(abs_path)
        if rec is None:
            raise ValueError("File exists. Read it first before overwriting.")
    # trackEdit 备份由 before_mutation 钩子在 handler 前调(commit 4 接线)。
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _runtime_state.read_file_state[abs_path] = _runtime_state.ReadRecord(
        content=content, mtime=path.stat().st_mtime, is_partial=False)
    return f"Wrote {file_path} ({len(content)} chars)"
