"""工具间共享状态(对标 CC readFileState + fileHistory 引用)。

阶段10:async 迁移后多 subagent 协程并发,scalar 改 contextvars 隔离(对标 CC AsyncLocalStorage)。
read_file_state 仍模块级 dict(单 agent 内共享;subagent 克隆留 TODO,对齐 CC cloneFileStateCache)。
阶段10 commit 10:加 agent_id contextvar,多 Agent tracing 用(Tracer 把它写进 span attrs)。
"""
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class ReadRecord:
    """读时刻的文件快照(对标 CC readFileState[path])。"""
    content: str
    mtime: float              # 读时刻的文件 mtime(Edit 陈旧检测比对)
    is_partial: bool = False  # offset/limit 读了部分 -> Edit 拒绝(对标 CC isPartialView)


# read_file_state 仍模块级 dict(单 agent 内共享;subagent 克隆留 TODO 阶段10)
read_file_state: dict[str, ReadRecord] = {}

# scalar 改 ContextVar:多 subagent 协程并发隔离(asyncio.Task 自动复制 context)
file_history: contextvars.ContextVar = contextvars.ContextVar("file_history", default=None)
current_step_id: contextvars.ContextVar = contextvars.ContextVar("current_step_id", default=0)
model_adapter: contextvars.ContextVar = contextvars.ContextVar("model_adapter", default=None)
workspace: contextvars.ContextVar = contextvars.ContextVar("workspace", default=None)
# commit 10:当前 agent 的 role(多 Agent tracing 用;Agent.run 设,Tracer 读进 span attrs)
agent_id: contextvars.ContextVar = contextvars.ContextVar("agent_id", default=None)


@contextmanager
def turn_context(adapter, ws, fh=None):
    """一轮 turn 的 ContextVar 注入(单一注入点,根除"各处手动 .set()"的泄漏风险)。

    - 设置模型适配器 / 工作区(工具 handler 经 _runtime_state.*.get() 读取)
    - fh 非 None 时也设置 file_history(版本链)
    - 退出恢复原值:防跨 turn / 跨 session 泄漏(漏设就拿到上一个 turn 的残留)
    调用方:Session.run_turn / agentloop / continue_loop(不再各自手动 .set())。
    current_step_id 由 runner._run_steps 每步设置(单一写者);agent_id 由 Agent.run 设/恢复。
    """
    prev = (model_adapter.get(), workspace.get(), file_history.get())
    model_adapter.set(adapter)
    workspace.set(ws)
    if fh is not None:
        file_history.set(fh)
    try:
        yield
    finally:
        model_adapter.set(prev[0])
        workspace.set(prev[1])
        file_history.set(prev[2])


def reset():
    """测试用:清空模块级状态 + 重置 contextvar,防测试间残留。"""
    read_file_state.clear()
    file_history.set(None)
    current_step_id.set(0)
    model_adapter.set(None)
    workspace.set(None)
    agent_id.set(None)
