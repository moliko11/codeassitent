# task 工具:主 agent 派子 agent(subagent)干子任务(CC "小弟"模型,阶段10 增强)
# 对标 CC Task 工具:主 agent 调本工具派一个子 agent 独立处理子任务,拿结果回来。
#
# 技术点:handler 同步(ToolExecutor 经 to_thread 跑),但 agent.run 是 async,handler 里不能 await。
# 故 handler 只返回请求标记 {"__subagent__": True, ...},agentloop._run_steps 拦截标记后异步跑子 agent
# (对标 NeedsApproval 的拦截模式),用子 agent 的最终回答替换 tool result。
#
# 注册方式:工厂 make_task_tool(),由 main() 注册到 REPL registry(对齐 make_save_memory_tool)。
from .defs import Tool, ToolSpec

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "子任务的简短描述(2-5 词,用于上下文/trace)"},
        "prompt": {"type": "string", "description": "给子 agent 的详细指令(子 agent 独立完成它)"},
    },
    "required": ["description", "prompt"],
}


def make_task_tool() -> Tool:
    """造 Task 工具。handler 只返回 subagent 请求标记;实际子 agent 由 agentloop._run_steps 拦截后异步跑。"""
    def handler(description: str, prompt: str):
        return {"__subagent__": True, "description": description, "prompt": prompt}
    return Tool(
        tool_spec=ToolSpec(
            name="task",
            description=(
                "派一个子 agent(小弟)独立完成一个子任务,返回它的结果。子 agent 有自己的上下文和工具,"
                "隔离运行(不继承本 agent 的对话历史,只看你给的 prompt)。用于:把复杂任务拆给子 agent、"
                "让子 agent 专注一个子问题。description=子任务简短描述;prompt=给子 agent 的详细指令。"
            ),
            input_schema=TASK_SCHEMA,
        ),
        handler=handler,
    )
