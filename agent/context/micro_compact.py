# 第 3 层压缩:MicroCompact -- 清老工具结果内容(低损)
#
# 对齐 cc services/compact/microCompact.ts + timeBasedMCConfig.ts:
#   工具结果随轮次价值递减。保留最近 K 个 tool_result 原文,更早的 content 清成
#   占位 [Old tool result content cleared](保留 call_id + 工具名,模型知道"这里曾有个 X 的结果")。
#
# 与步 3(ToolResultBudget)协同:
#   - 步 3 把大结果落盘成 <persisted-output> 引用(无损,模型可 Read 回)
#   - 步 4 清"没被步 3 落盘的、且过老"的 tool_result content(低损)
#   - 已落盘的引用(persisted-output)不清--清了模型就读不回全文了
#
# cc 的 timeBasedMCConfig:gapThresholdMinutes=60(cache 必过期)+ keepRecent=5。
# 本版简化:按"轮次距离"衰减(保留最近 K 个),不接 cache TTL。
from ..core.messages import Message
from .budget import PERSISTED_TAG

CLEARED_MESSAGE = "[Old tool result content cleared]"


def _is_tool_result(msg: Message) -> bool:
    """识别 role=tool 的消息(同 budget.py 判据;结构化后只看 role)。"""
    return msg.role == "tool"


def _is_persisted_reference(text) -> bool:
    """是否是步3落盘后的引用(已无损存盘,不再清)。"""
    return isinstance(text, str) and text.startswith(PERSISTED_TAG)


def micro_compact(messages: list[Message], keep_recent: int = 3) -> list[Message]:
    """第 3 层压缩:清老 tool_result content 成占位(低损)。

    保留最后 keep_recent 个 tool_result 的原文,更早的:
      - 若是步3落盘的引用(persisted-output):保留(模型可 Read 回,无损)
      - 若是原始文本:清成 CLEARED_MESSAGE(低损)
    不改入参 Message 对象(新建 Message 替换)。
    """
    tool_indices = [i for i, m in enumerate(messages) if _is_tool_result(m)]
    if len(tool_indices) <= keep_recent:
        return messages  # 没超过保留数,不动
    # 要清的:除最后 keep_recent 个之外的 tool_result
    to_clear = set(tool_indices[:-keep_recent]) if keep_recent > 0 else set(tool_indices)

    out: list[Message] = []
    for i, msg in enumerate(messages):
        if i not in to_clear:
            out.append(msg)
            continue
        text = msg.content
        if _is_persisted_reference(text):
            out.append(msg)  # 落盘引用保留(模型可 Read 回)
            continue
        # 原始文本 -> 清成占位(新建 Message,不动原对象;meta 保留)
        out.append(Message(role=msg.role, content=CLEARED_MESSAGE, meta=msg.meta))
    return out