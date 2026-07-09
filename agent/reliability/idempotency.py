# IdempotencyStore：幂等去重缓存，按 key 缓存「成功结果」，防止重复副作用。
#
# 对应面试题 12-16。key 默认用 tool_call_id（天然幂等键，呼应题 5/6 的 call_id）；
# 生产中更稳的是用客户端传入的 idempotency_key（见 key_fn 参数）：同一逻辑请求可能
# 带不同 call_id（如模型重试时生成新 id），此时 call_id 去重会失效。
#
# 只缓存成功结果：失败不缓存，允许重试。in-flight 并发去重未做（本阶段单步串行执行）。
#
# 不 import ToolCall：用 Any + 鸭子类型（call.call_id），保持 reliability 纯净无环。
from __future__ import annotations

from typing import Any, Callable


class IdempotencyStore:
    """幂等去重缓存，按 key 缓存「成功结果」，防止重复副作用。"""
    def __init__(self, key_fn: Callable[[Any], str] | None = None):
        # 默认 key = call.call_id；可传 key_fn=lambda c: c.arguments["idempotency_key"]
        self._store: dict[str, Any] = {}
        self._key_fn = key_fn or (lambda call: call.call_id)

    def _key(self, call) -> str:
        return self._key_fn(call)

    def get(self, call) -> Any | None:
        """命中返回缓存结果，未命中返回 None。"""
        return self._store.get(self._key(call))

    def has(self, call) -> bool:
        return self._key(call) in self._store

    def set(self, call, result: Any) -> None:
        """缓存一次成功结果。"""
        self._store[self._key(call)] = result
