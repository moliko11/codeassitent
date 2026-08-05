"""Grep 工具:正则搜索文件内容(对标 CC GrepTool,基于 ripgrep)。

简化:只用 Python re 扫(跨平台、无 rg 依赖)。TODO: 优先调系统 rg(快),无则 fallback。
output_mode:files_with_matches(默认,文件路径列表)/ content(带行号)/ count(每文件匹配数)。
"""
import fnmatch
import re
from pathlib import Path

from ..registry import tool
from .. import _runtime_state

GREP_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "正则表达式"},
        "path": {"type": "string", "description": "搜索根目录或单文件,默认当前目录"},
        "glob": {"type": "string", "description": "文件名过滤(如 *.py)"},
        "output_mode": {"type": "string", "enum": ["files_with_matches", "content", "count"],
                        "description": "默认 files_with_matches"},
    },
    "required": ["pattern"],
}


@tool(
    name="grep",
    description=(
        "正则搜索文件内容,定位代码位置。"
        "探索未知代码库时:先用 output_mode=files_with_matches(默认)找出哪些文件命中,"
        "再用 output_mode=content 看具体行--不要一上来就读整个文件。"
        "output_mode: files_with_matches(路径列表)/content(带行号)/count。"
    ),
    input_schema=GREP_SCHEMA,
    mutates_external=False,
)
def grep(pattern, path=".", glob=None, output_mode="files_with_matches"):
    ws = _runtime_state.workspace.get()
    if ws and not ws.allows(path):
        raise PermissionError(f"路径不在工作空间允许集内: {path}")
    base = ws.resolve(path) if ws else Path(path)
    regex = re.compile(pattern)
    # 收集待搜文件
    if base.is_file():
        files = [base]
    else:
        files = [p for p in base.rglob("*") if p.is_file()]
        if glob:
            files = [p for p in files if fnmatch.fnmatch(p.name, glob)]
    # 扫描
    results: dict[Path, list[tuple[int, str]]] = {}   # {file: [(lineno, line), ...]}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ms = [(i + 1, ln) for i, ln in enumerate(text.splitlines()) if regex.search(ln)]
        if ms:
            results[f] = ms
    if output_mode == "files_with_matches":
        return [str(f) for f in results]
    if output_mode == "count":
        return {str(f): len(ms) for f, ms in results.items()}
    # content: 带行号
    return [f"{f}:{lineno}:{ln}" for f, ms in results.items() for lineno, ln in ms]
