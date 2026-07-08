from enum import Enum


class Action(Enum):
    FINISH        = "finish"        # 无 tool_calls，输出最终答案
    CALL_TOOLS    = "call_tools"    # 有 tool_calls
    HANDLE_ERROR  = "handle_error"  # 空响应/异常格式

def decide(model_response) -> Action:
    """根据模型响应内容，决定下一步动作"""
    if model_response.tool_calls:
        return Action.CALL_TOOLS
    if model_response.text:          # 有文本、无工具 -> 结束
        return Action.FINISH
    return Action.HANDLE_ERROR       # 既无文本也无工具 -> 异常
