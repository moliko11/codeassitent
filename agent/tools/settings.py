# agent/tools/settings.py —— 工具超时/截断参数(读 tools.yaml)
#
# 为什么模块级全局:各 @tool handler 是独立函数,签名带 Python 默认(如 bash timeout=30)。
# 装配点(agentloop main / chatweb server)调 configure_tools(get_section("tools")) 注入 tools.yaml 段,
# handler 内用 t("bash.default_timeout", 30) 取:配置了用配置,没配置回落 Python 默认(行为与现状逐位一致)。
# 测试不调 configure_tools -> _CFG 恒 None -> 全回落默认,不破坏。
from __future__ import annotations

_CFG: dict | None = None


def configure_tools(cfg: dict | None) -> None:
    """装配处注入 tools.yaml 的 tools 段。None=回落代码默认。"""
    global _CFG
    _CFG = cfg or None


def t(path: str, default):
    """按点分路径读 tools 参数: t("bash.default_timeout", 30)。未 configure / 缺 key -> default。"""
    if _CFG is None:
        return default
    cur: object = _CFG
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
