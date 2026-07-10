# 测试用工具：Tavily 联网搜索 / 按行读文件 / grep 关键词查找
# 不追求生产级，仅用于测试 Agent 工具调用链路
import os

import httpx

from .registry import tool


@tool(
    name="tavily_search",
    description="联网搜索（Tavily API）。输入查询词，返回前 N 条结果的标题、URL、内容摘要。用于获取模型不知道的最新信息。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {"type": "integer", "description": "返回结果数，默认 3"},
        },
        "required": ["query"],
    },
    returns="list[{title, url, content}]",
)
def tavily_search(query: str, max_results: int = 3):
    api_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVIL_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 TAVILY_API_KEY 环境变量")
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": max_results},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    # 只取摘要字段，content 截断 300 字符，避免结果过长
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": (r.get("content") or "")[:300],
        }
        for r in data.get("results", [])
    ]


@tool(
    name="read_file_lines",
    description="按行读取文本文件，支持指定行范围（start_line 到 end_line）。返回带行号的内容。用于查看文件局部内容。",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "文件路径"},
            "start_line": {"type": "integer", "description": "起始行号(从1开始)，默认 1"},
            "end_line": {"type": "integer", "description": "结束行号(含)，不填则到文件末尾"},
        },
        "required": ["file_path"],
    },
    returns="str: 带行号的文件内容片段",
)
def read_file_lines(file_path: str, start_line: int = 1, end_line: int | None = None):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    total = len(lines)
    start = max(1, start_line)
    end = total if end_line is None else min(end_line, total)
    if start > end:
        return f"行范围无效: start={start}, end={end}, 总行数={total}"
    out = [f"{i + 1}: {lines[i].rstrip()}" for i in range(start - 1, end)]
    return f"共 {total} 行，显示第 {start}-{end} 行:\n" + "\n".join(out)


@tool(
    name="grep_search",
    description="在文本文件中查找关键词，返回所有匹配行（带行号）。用于快速定位文件中包含某关键词的位置。",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "文件路径"},
            "keyword": {"type": "string", "description": "要查找的关键词"},
        },
        "required": ["file_path", "keyword"],
    },
    returns="str: 匹配行(行号:内容)",
)
def grep_search(file_path: str, keyword: str):
    matches = []
    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if keyword in line:
                matches.append(f"{i}: {line.rstrip()}")
    if not matches:
        return f"未找到关键词 '{keyword}'"
    return f"找到 {len(matches)} 处匹配:\n" + "\n".join(matches)
