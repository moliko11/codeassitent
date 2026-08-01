"""WebFetch 工具:抓 URL 内容并用 LLM 按 prompt 提取(可直接抄 CC)。

httpx 抓 + HTML->text + model_adapter 调 LLM 提取(对标 CC 用 small fast model,不复用主对话上下文)。
- HTTP 自动升 HTTPS;跨域重定向不跟随,返回 REDIRECT 让模型重 fetch(对标 CC WebFetchTool.ts:217-249)。
- 简化:15min 缓存 / 二进制(PDF)落盘 / 预批准域名 都留 TODO。
- model_adapter 经 _runtime_state 全局注入(同 file_history 模式,agentloop 注入)。
"""
import html as html_mod
import re

import httpx

from ..registry import tool
from .. import _runtime_state
# ModelRequest/Message 延迟到 web_fetch 内 import:顶部 import 会与 core.models 循环
# (tools/__init__ 初始化时 import 本模块,本模块 import core.models,core.models 又 import tools.defs -> tools/__init__)。

WEB_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "要抓的 URL"},
        "prompt": {"type": "string", "description": "对抓回的内容要提取什么"},
    },
    "required": ["url", "prompt"],
}


def _html_to_text(html: str) -> str:
    """简版 HTML->text:去 script/style/标签 + 实体 + 压缩空行。TODO: 用 html2text 更好。"""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<(p|div|br|h[1-6]|li|tr)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    html = html_mod.unescape(html)
    html = re.sub(r"\n\s*\n+", "\n\n", html)
    return html.strip()


@tool(
    name="web_fetch",
    description="抓 URL 内容并用 LLM 按 prompt 提取。HTTP 自动升 HTTPS;跨域重定向返回提示不跟随。",
    input_schema=WEB_FETCH_SCHEMA,
    mutates_external=False,
)
def web_fetch(url, prompt):
    # 1. HTTP 升 HTTPS
    if url.startswith("http://"):
        url = "https://" + url[7:]
    if not url.startswith("https://"):
        return {"error": "无效 URL,需 http(s)://"}
    # 2. 抓(不跟随重定向)
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=False)
    except httpx.HTTPError as e:
        return {"error": f"网络错误: {e}"}
    # 3. 跨域重定向不跟随,返回让模型重 fetch(对标 CC;简化:所有重定向都不跟随)
    if resp.is_redirect:
        loc = resp.headers.get("location", "")
        return f"REDIRECT to {loc}, please re-fetch with the new URL."
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}"}
    # 4. HTML -> text
    markdown = _html_to_text(resp.text)
    # 5. 用 model_adapter 调 LLM 提取(对标 CC small model,不复用主对话上下文)
    adapter = _runtime_state.model_adapter.get()
    if adapter is None:
        return {"error": "无 model_adapter(未注入),无法提取"}
    from ...core.models import ModelRequest   # 延迟 import 避免循环
    from ...core.messages import Message
    import asyncio
    result = asyncio.run(adapter.call_llm(ModelRequest(messages=[
        Message(role="system", content="按 prompt 从网页内容提取,简洁回答"),
        Message(role="user", content=f"网页内容:\n{markdown[:8000]}\n\n问题:{prompt}"),
    ])))
    return result.text
