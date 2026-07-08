# 全局枚举与类型别名（纯 Literal，无业务依赖，处于最底层）
# 所有模块共享的状态/角色定义集中在此，避免散落在 models / messages 多处
#
# 设计说明：用 Literal 而非 Enum。
# Role / ContentType 需要和 OpenAI/DeepSeek API 的字符串契约直接对接
# （如 message.role 必须是 "user" 字符串），Literal 运行时即字符串，零转换成本。
# AgentStatus 是内部状态，同样用 Literal 保持全项目风格一致。
from typing import Literal

# 对话角色
Role = Literal["system", "user", "assistant", "tool"]

# Agent 运行状态（可序列化）
AgentStatus = Literal[
    "created",            # 已创建未启动
    "running",            # 运行中
    "waiting_tool",       # 等待工具执行
    "waiting_approval",   # 等待人工审批
    "completed",          # 正常完成
    "failed",             # 运行失败
    "cancelled",          # 主动取消
    "max_steps_exceeded", # 超过最大步数限制
]

# 内容块类型（精细化消息结构使用）
ContentType = Literal["text", "image", "tool_use", "tool_result", "reasoning"]
