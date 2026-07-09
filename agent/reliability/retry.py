# RetryPolicy：工具执行的重试策略（指数退避 + jitter）。
#
# 对应面试题 6/8/9：什么该重试、退避公式、jitter 防惊群。
#
# 退避：delay = min(base * 2**attempt, max_delay) + uniform(0, jitter)
# - 指数部分：每次失败后等待时间翻倍，给上游/下游恢复时间。
# - max_delay 封顶：避免单次退避过长拖死整轮。
# - jitter（随机抖动）：多个并发调用同时失败时，加随机量错开重试，防止「惊群」
#   在同一时刻同时重打刚刚恢复的下游。
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class RetryPolicy:
    max_attempts: int = 3            # 含首次；总尝试次数（max_attempts=1 即不重试）
    base_delay: float = 0.5          # 首次重试前等待基数（秒）
    max_delay: float = 10.0          # 单次退避上限（秒）
    jitter: float = 0.1              # 随机抖动上限（秒）

    def backoff(self, attempt: int) -> float:
        """第 attempt 次失败后到下一次重试前的等待时间（attempt 从 0 起）。"""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        return delay + random.uniform(0, self.jitter)

    def should_retry(self, error: dict) -> bool:
        """根据结构化 error dict 的 retryable 字段决定是否重试。"""
        return bool(error.get("retryable", False))
