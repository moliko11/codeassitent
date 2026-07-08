
import json

from ..tools.defs import ToolCall
class LoopDetector:
    """
    检测 Agent 陷入"重复调用相同工具+相同参数"的循环。
    与 max_consecutive_tool_failures 正交：后者检测连续失败（成功时被清零），
    本检测器检测连续重复（无论成功失败都观察签名）。失败循环由 fail 兜底，
    成功但重复的循环由本检测器发软终止提醒。
    """
    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self._last_sig:str | None = None # 上一轮工具调用签名
        self._streak: int = 0 # 连续重复次数

    def _signature(self, tool_calls:list[ToolCall]) -> str:
        """计算本轮工具调用签名"""
        items = []
        for tc in tool_calls:
            # 一轮多个tool_calls:按照(name，args_hash)排序后拼接成签名
            args_hash=hash(json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)) if tc.arguments else 0
            items.append(f"{tc.tool_name}:{args_hash}")

        items.sort()
        return repr(items)
    def observe(self, tool_calls: list[ToolCall]):
        """记录本轮工具调用签名，更新连续计数"""
        sig = self._signature(tool_calls)
        if sig == self._last_sig:
            self._streak += 1
        else:
            self._streak = 1
            self._last_sig = sig
    def is_looping(self) -> bool:
        return self._streak >= self.threshold
    
    def reset(self):
        """软终止提醒注入后重置，给模型换方法的机会（避免每轮都提醒）"""
        self._last_sig = None
        self._streak = 0