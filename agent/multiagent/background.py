# multiagent/background.py - 后台 subagent(阶段10 commit 9,题19/20)
# fire-and-forget 跑 subagent:asyncio.create_task 不 await,完成时往 notify_queue put (role, text),
# 主循环(run_agent_loop 的 notify_queue 排干,commit 6)把它作为 [task-notification] user 消息注入下轮。
# 对标 CC runAsyncAgentLifecycle(agentToolUtils.ts:508)+ <task-notification>(LocalAgentTask.tsx:197)。
#
# contextvar 隔离:asyncio.create_task 自动复制当前 context(Step 5 的 _runtime_state contextvars),
# subagent 在自己的 context copy 里跑,model_adapter/workspace/current_step_id 不污染父(对标 CC AsyncLocalStorage)。
import asyncio

from .agent import Agent, subagent_result_text, subagent_status


# 持强引用防 fire-and-forget Task 被 GC 取消(asyncio 已知坑:create_task 返回的 Task 不持引用会被回收)
_background_tasks: set = set()


async def run_subagent_background(agent: Agent, task: str, notify_queue: asyncio.Queue) -> None:
    """跑一个 subagent,完成时把 (role, final_text, status) put 到 notify_queue。

    通常用 launch_background_subagent 包成 asyncio.create_task fire-and-forget;
    直接 await 则等价于串行 subagent(失去后台语义,但便于测试)。

    final_text 有 final_response 用其文本,未完成用 subagent_result_text 的失败原因;
    status 用 subagent_status(completed/failed/stopped,对齐 CC 通知 <status>),
    主 agent 收到 [task-notification] 即知子 agent 成败,自行兜底,不再等空结果。
    """
    state = await agent.run(task)
    await notify_queue.put((agent.role, subagent_result_text(state), subagent_status(state)))


def launch_background_subagent(agent: Agent, task: str, notify_queue: asyncio.Queue) -> asyncio.Task:
    """fire-and-forget 启动后台 subagent:asyncio.create_task 不 await,立即返回 Task。

    完成时 run_subagent_background 往 notify_queue put (role, text),主循环排干时注入下轮。
    Task 在当前 context 的 copy 里跑(contextvar 隔离,Step 5)。
    """
    t = asyncio.create_task(run_subagent_background(agent, task, notify_queue))
    _background_tasks.add(t)            # 持强引用防 GC(asyncio Task 不持引用会被回收/取消)
    t.add_done_callback(_background_tasks.discard)
    return t
