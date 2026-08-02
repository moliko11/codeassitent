"""Read 工具:读文本文件,返回 cat -n 带行号内容;读后记 read_file_state(供 Edit 先读后改 + 陈旧检测)。

对标 CC FileReadTool:Read 记 readFileState[path] = {content, mtime, isPartialView},
Edit/Write 改该文件前查它(先读后改 + 陈旧检测)。
"""
from pathlib import Path

from ..registry import tool
from .. import _runtime_state

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "文件路径(绝对或相对)"},
        "offset": {"type": "integer", "description": "起始行(1-based),默认 1"},
        "limit": {"type": "integer", "description": "读取行数,默认到文件末尾"},
    },
    "required": ["file_path"],
}


@tool(
    name="read",
    description=(
        "读文本文件,返回 cat -n 带行号内容。默认读全文。"
        "大文件(>300 行)务必用 offset+limit 分段读,不要一次性加载。"
        "已经读过的文件不要重复全量读--如需回看用 offset 精确定位行号。"
        "读后记录文件状态,Edit/Write 改该文件前必须先 Read。"
    ),
    input_schema=READ_SCHEMA,
    returns="str: 带行号的内容",
    mutates_external=False,
)
def read(file_path, offset=None, limit=None):
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if path.is_dir():
        raise IsADirectoryError(f"路径是目录,不是文件: {path}")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    total = len(lines)
    start = max(1, offset) if offset is not None else 1
    end = (start - 1 + limit) if limit is not None else total
    end = min(end, total)
    selected = lines[start - 1:end]
    numbered = "\n".join(f"{start + i}\t{ln}" for i, ln in enumerate(selected))
    # 记 read_file_state:全量读记有效状态(供 Edit 校验);部分读标 is_partial(Edit 拒绝,对标 CC isPartialView)。
    is_partial = offset is not None or limit is not None
    _runtime_state.read_file_state[str(path)] = _runtime_state.ReadRecord(
        content=content, mtime=path.stat().st_mtime, is_partial=is_partial)
    return numbered   # cat -n 格式;空文件返回 ""


# 注:数据类(ReadFileInput/TextFile/ImageFile/...)已挪到 types.py,供后续多模态扩展。
