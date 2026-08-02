# multiagent/blackboard.py - 多 Agent 共享状态(阶段10,题10/11)
# 对标 CC:多 agent 间靠共享上下文/工具结果传递;我们用 Blackboard(共享 dict + asyncio.Lock)。
# worker 结果写 blackboard,orchestrator/其他 worker 读 snapshot(注入 task)看到共享状态。
import asyncio
from typing import Any


class Blackboard:
    """多 Agent 共享状态。async 读写(asyncio.Lock 协作互斥,单事件循环下防并发交错)。

    用法:orchestrator 持有一个 Blackboard,handoff 给 worker 时传入;worker 跑完把
    final_response 写回 blackboard.set(role, text);下一轮 orchestrator/worker 经
    snapshot() 看到所有 worker 的结果。
    """

    def __init__(self):
        self.data: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self.data[key] = value

    async def get(self, key: str) -> Any:
        async with self._lock:
            return self.data.get(key)

    def snapshot(self) -> str:
        """同步快照(注入 task 让模型看到共享状态)。

        安全性:single event loop 下 sync 读期间无 await,无协程交错 mutate data,
        故无需持锁(锁也非可重入的同步锁)。空 blackboard 返回空串。
        """
        return "\n".join(f"[{k}] {v}" for k, v in self.data.items())
