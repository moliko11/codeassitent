"""WebSearch 工具:联网搜索(接 Tavily,CC 抄不了)。

CC 的 WebSearch 借 Anthropic 服务端 web_search tool,DeepSeek/豆包没有,接 Tavily 第三方 API。
结果格式化对标 CC:标题+url+摘要,末尾附 Sources markdown 链接(CC prompt 强制 "never skip sources")。
- mutates_external=False,只读。
- 参数错误(query 空 / allowed+blocked 同传)抛 ValueError;网络/key 错误返回结构化 error(不抛,对标文档)。
"""
import os

import httpx

from ..registry import tool

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索关键词"},
        "allowed_domains": {"type": "array", "items": {"type": "string"},
                             "description": "仅搜这些域名"},
        "blocked_domains": {"type": "array", "items": {"type": "string"},
                            "description": "排除这些域名"},
        "max_results": {"type": "integer", "description": "返回结果数,默认 5"},
    },
    "required": ["query"],
}


@tool(
    name="web_search",
    description="联网搜索(Tavily)。返回标题+url+摘要,末尾附 Sources。用于获取模型不知道的最新信息。",
    input_schema=WEB_SEARCH_SCHEMA,
    mutates_external=False,
)
def web_search(query, allowed_domains=None, blocked_domains=None, max_results=5):
    if not query or not str(query).strip():
        raise ValueError("query 不能为空")
    if allowed_domains and blocked_domains:
        raise ValueError("不能同时传 allowed_domains 和 blocked_domains")
    api_key = os.environ.get("TAVILY_API_KEY") or os.environ.get("TAVIL_API_KEY")
    if not api_key:
        return {"error": "未设置 TAVILY_API_KEY/TAVIL_API_KEY 环境变量"}
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_domains": allowed_domains or [],
                "exclude_domains": blocked_domains or [],
            },
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"网络错误: {e}"}
    data = resp.json()
    results = data.get("results", [])
    # 格式化:每条 标题+url+摘要(截 300);末尾 Sources markdown 链接(对标 CC 强制)
    blocks = [
        f"### {r.get('title', '')}\n{r.get('url', '')}\n{(r.get('content') or '')[:300]}"
        for r in results
    ]
    body = "\n\n".join(blocks) if blocks else "无结果"
    if not results:
        return body
    sources = "\n".join(f"- [{r.get('title', '')}]({r.get('url', '')})" for r in results)
    return f"{body}\n\nSources:\n{sources}"
