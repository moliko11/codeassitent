# CircuitBreaker：熔断器，per-tool 保护，防止对持续失败的下游疯狂重试。
#
# 对应面试题 11。三态机：
# - closed（闭路）：正常放行，累计失败计数；达 failure_threshold -> open。
# - open（开路）：直接拒绝（不真实调用），等 recovery_timeout 后转 half_open。
# - half_open（半开）：放行 1 次试探；成功 -> closed，失败 -> open。
#
# 设计：查询时「懒推进」open->half_open（避免后台定时器），单线程下足够。
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

BreakerState = Literal["closed", "open", "half_open"]


@dataclass
class BreakerConfig:
    failure_threshold: int = 5       # 连续失败达此值 -> 开路
    recovery_timeout: float = 10.0   # 开路后多久允许半开试探（秒）
    half_open_max: int = 1           # 半开态允许的试探次数


class CircuitBreaker:
    """熔断器，per-tool 保护，防止对持续失败的下游疯狂重试。

    线程安全:_parallel 用 asyncio.to_thread 并发跑同一工具的多个调用,共享 per-tool breaker,
    故状态推进/失败计数/半开 inflight 都加锁(RLock:allow_request 内调 state 可重入)。"""
    def __init__(self, config: BreakerConfig | None = None):
        self.config = config or BreakerConfig()
        self._state: BreakerState = "closed"
        self._failures: int = 0
        self._opened_at: float | None = None      # open 起始时刻（monotonic）
        self._half_open_inflight: int = 0          # 半开态已放行的试探数
        self._lock = threading.RLock()             # _parallel 并发下保护状态机

    @property
    def state(self) -> BreakerState:
        with self._lock:
            # 懒推进：查询时若 open 已过 recovery_timeout，转 half_open
            if self._state == "open" and self._opened_at is not None:
                if time.monotonic() - self._opened_at >= self.config.recovery_timeout:
                    self._state = "half_open"
                    self._half_open_inflight = 0
            return self._state

    def allow_request(self) -> bool:
        """是否允许真实调用。open（未到恢复时间）-> 拒绝；其余放行。"""
        with self._lock:
            s = self.state  # 触发懒推进(RLock 可重入)
            if s == "open":
                return False
            if s == "half_open":
                if self._half_open_inflight >= self.config.half_open_max:
                    return False
                self._half_open_inflight += 1
                return True
            return True  # closed

    def record_success(self):
        """调用成功：half_open 试探成功 -> 恢复闭路；清零失败计数。"""
        with self._lock:
            if self._state == "half_open":
                self._state = "closed"
            self._failures = 0
            self._half_open_inflight = 0

    def record_failure(self):
        """调用失败：累计计数；half_open 试探失败 -> 重新开路；closed 达阈值 -> 开路。"""
        with self._lock:
            self._failures += 1
            if self._state == "half_open":
                self._open()
            elif self._failures >= self.config.failure_threshold:
                self._open()

    def _open(self):
        self._state = "open"
        self._opened_at = time.monotonic()
