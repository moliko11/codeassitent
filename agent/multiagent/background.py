# multiagent/background.py - 后台 subagent(阶段10 commit 9,题19/20)
# fire-and-forget 跑 subagent:asyncio.create_task 不 await,完成时往 notify_queue put (role, text),
# 主循环(run_agent_loop 的 notify_queue 排干,commit 6)把它作为 [task-notification] user 消息注入下轮。
# 对标 CC runAsyncAgentLifecycle(agentToolUtils.ts:508)+ <task-notification>(LocalAgentTask.tsx:197)。
#
# contextvar 隔离:asyncio.create_task 自动复制当前 context(Step 5 的 _runtime_state contextvars),
# subagent 在自己的 context copy 里跑,model_adapter/workspace/current_step_id 不污染父(对标 CC AsyncLocalStorage)。
import asyncio

from .agent import Agent


async def run_subagent_background(agent: Agent, task: str, notify_queue: asyncio.Queue) -> None:
    """跑一个 subagent,完成时把 (role, final_text) put 到 notify_queue。

    通常用 launch_background_subagent 包成 asyncio.create_task fire-and-forget;
    直接 await 则等价于串行 subagent(失去后台语义,但便于测试)。
    """
    state = await agent.run(task)
    text = getattr(state.final_response, "text", "") if state.final_response else ""
    await notify_queue.put((agent.role, text))


def launch_background_subagent(agent: Agent, task: str, notify_queue: asyncio.Queue) -> asyncio.Task:
    """fire-and-forget 启动后台 subagent:asyncio.create_task 不 await,立即返回 Task。

    完成时 run_subagent_background 往 notify_queue put (role, text),主循环排干时注入下轮。
    Task 在当前 context 的 copy 里跑(contextvar 隔离,Step 5)。
    """
    return asyncio.create_task(run_subagent_background(agent, task, notify_queue))
