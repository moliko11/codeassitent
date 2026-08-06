# task 工具:主 agent 派子 agent(subagent)干子任务(CC "小弟"模型,阶段10 增强)
# 对标 CC Task 工具:主 agent 调本工具派一个子 agent 独立处理子任务,拿结果回来。
#   background=false(默认,前台):等子 agent 跑完,结果作为 tool result 当场返回。
#   background=true(后台):fire-and-forget,主 agent 立即继续做别的,子 agent 完成后经
#     notify_queue -> [task-notification] 下轮注入(对标 CC Task background)。
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
        "background": {"type": "boolean", "description": "是否后台运行(默认 false)。false=等子 agent 跑完拿结果;true=派出去不等,主 agent 立即继续做别的,子 agent 完成后以 [task-notification] 通知"},
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
                "\n\n前台 vs 后台(按需选,对标 CC Task 工具):"
                " 前台(background=false,默认)=主 agent 阻塞等子 agent 跑完,结果当场拿到;"
                "用于【需要子 agent 结果才能继续】的场景(如调研发现决定下一步、结果要进最终答案)。"
                " 后台(background=true)=主 agent 不等、立即继续做别的,子 agent 完成后以 [task-notification] "
                "通知(下轮注入);用于【有真正独立的并行工作】的场景。"
                "后台子 agent 跑完会自动通知,不要 sleep/轮询/主动查进度。"
            ),
            input_schema=TASK_SCHEMA,
        ),
        handler=handler,
    )
