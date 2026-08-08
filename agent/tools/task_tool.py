# task 工具:主 agent 派子 agent(subagent)干子任务(CC "小弟"模型,阶段10 增强)
# 对标 CC Task 工具:主 agent 调本工具派一个子 agent 独立处理子任务,拿结果回来。
#   background=false(默认,前台):阻塞等子 agent 跑完,结果作为 tool result 当场返回(一轮收尾)。
#   background=true(后台):fire-and-forget,主 agent 立即继续做别的,子 agent 完成后经
#     notify_queue -> [task-notification] 下轮注入。
#
# 2026-08-08 默认从 true 改回 false(对齐 CC AgentTool prompt.ts:263 "Use foreground (default)
# when you need the agent's results before you can proceed")。2026-08-07 曾因"前台 Task 在
# execute_many 批次内 await 把主循环冻住 ~266s"改成默认后台,代价是"最终回答需要子 agent 结果"
# 的任务被拆成两轮(主 agent 收尾 -> [task-notification] 自动起新一轮),用户视为一轮。
# 前台默认 + 一批多个前台子 agent 并行派(待办 D)恢复"一轮收尾且并行",后台只留给真正独立的
# 并行工作。详见 docs/topics/session-issue-analysis.md。
#
# 技术点:handler 同步(ToolExecutor 经 to_thread 跑),但 agent.run 是 async,handler 里不能 await。
# 故 handler 只返回请求标记 {"__subagent__": True, ...},agentloop._run_steps 拦截标记后异步跑子 agent
# (对标 NeedsApproval 的拦截模式):前台 await 等结果 / 后台 asyncio.create_task fire-and-forget。
from .defs import Tool, ToolSpec

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "子任务的简短描述(2-5 词,用于上下文/trace)"},
        "prompt": {"type": "string", "description": "给子 agent 的详细指令(子 agent 独立完成它)"},
        "background": {"type": "boolean", "description": "是否后台运行(默认 false)。false=等子 agent 跑完拿结果,一轮收尾(默认);true=派出去不等,主 agent 立即继续做别的,子 agent 完成后以 [task-notification] 通知"},
    },
    "required": ["description", "prompt"],
}


def make_task_tool() -> Tool:
    """造 Task 工具。handler 只返回 subagent 请求标记;实际子 agent 由 agentloop._run_steps 拦截后异步跑。"""
    def handler(description: str, prompt: str, background: bool = False):
        return {"__subagent__": True, "description": description,
                "prompt": prompt, "background": background}
    return Tool(
        tool_spec=ToolSpec(
            name="task",
            description=(
                "派一个子 agent(小弟)独立完成一个子任务,返回它的结果。子 agent 有自己的上下文和工具,"
                "隔离运行(不继承本 agent 的对话历史,只看你给的 prompt)。用于:把复杂任务拆给子 agent、"
                "让子 agent 专注一个子问题。"
                "description=子任务简短描述;prompt=给子 agent 的详细指令;background=是否后台(默认 false)。"
                "\n\n前台 vs 后台(对标 CC Task 工具):"
                " 前台(background=false,默认)=主 agent 等子 agent 跑完,结果当场拿到,一轮收尾;"
                "用于【最终回答需要子 agent 结果】的场景(如调研结果要汇总进答案)——需要多个子 agent 时"
                "一次并行派,别拆多轮。"
                " 后台(background=true)=主 agent 不等、立即继续做别的,子 agent 完成后以 [task-notification] "
                "通知(下轮注入);仅用于【主 agent 有真正独立的并行工作、不依赖子 agent 结果也能收尾】的场景。"
                "后台子 agent 跑完会自动通知,不要 sleep/轮询/主动查进度。"
            ),
            input_schema=TASK_SCHEMA,
        ),
        handler=handler,
    )
