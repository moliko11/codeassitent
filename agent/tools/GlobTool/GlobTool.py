"""Glob 工具:按文件名模式找文件(对标 CC GlobTool)。

pathlib.glob 支持 ** 递归;结果按 mtime 倒序(最近修改在前,对标 CC)。
"""
from pathlib import Path

from ..registry import tool

GLOB_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "glob 模式(如 **/*.py)"},
        "path": {"type": "string", "description": "搜索根目录,默认当前目录"},
    },
    "required": ["pattern"],
}


@tool(
    name="glob",
    description="按文件名模式找文件(如 **/*.py),按 mtime 倒序(最近修改在前)。",
    input_schema=GLOB_SCHEMA,
    mutates_external=False,
)
def glob(pattern, path="."):
    base = Path(path)
    matches = [p for p in base.glob(pattern) if p.is_file()]
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in matches]
