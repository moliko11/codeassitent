# 第 5 层压缩:AutoCompact -- 全量摘要兜底(有损)
#
# 对齐 cc services/compact/autoCompact.ts + compact.ts 的 buildPostCompactMessages:
#   触发:步3(无损)+步4(低损)后 token 仍超 budget -> 调一次 LLM 把老消息摘要成
#   一条 summary,保留 system + 最近 N 轮 + summary。有损,所以是最后兜底。
#
# 压缩边界(对齐 cc getMessagesAfterCompactBoundary):摘要后 messages =
# [system, summary_msg, 最近N轮]。summary_msg 即边界。
#
# 简化(与 cc 差异,见末"已知简化"):
#   - cc 跨轮记忆压缩边界(避免每轮重新摘要,保 prompt cache);本版每轮按需摘要
#     (over_budget 才触发,不常发生)。跨轮记忆见"进阶"。
#   - cc 摘要用专门 prompt + 结构化 attachments;本版用简单 system prompt。
#   --后面抄cc的提示词。
from typing import Callable, Optional

from ..core.messages import Message
from ..core.models import ModelRequest

SUMMARY_SYSTEM_PROMPT = (
    "请把以下对话历史压缩成要点摘要,保留关键事实、用户意图和工具结论。"
    "用简洁的中文输出,不要遗漏关键信息。"
)


async def auto_compact(
    messages: list[Message],
    summarizer: Callable[[list[Message]], str],
    keep_recent_turns: int = 4,
) -> list[Message]:
    """第 5 层压缩:超 budget 时摘要老消息(有损兜底)。

    保留 system 消息(头部) + 最后 keep_recent_turns 条消息(尾部),
    中间的老消息调 summarizer 压成一条 summary(system 角色),插在 system 之后。
    不改入参 Message 对象。
    """
    if not messages:
        return messages
    # 分离 system 头部(只认第一条,多 system 不常见)
    system_msgs: list[Message] = []
    rest = messages
    if messages[0].role == "system":
        system_msgs = [messages[0]]
        rest = messages[1:]
    if len(rest) <= keep_recent_turns:
        return messages  # 没东西可摘要
    to_summarize = rest[:-keep_recent_turns] if keep_recent_turns > 0 else rest
    kept = rest[-keep_recent_turns:] if keep_recent_turns > 0 else []

    summary_text = await summarizer(to_summarize)
    summary_msg = Message(
        role="system",
        content=f"[之前的对话摘要]\n{summary_text}",
    )
    return system_msgs + [summary_msg] + kept


def make_summarizer(model_adapter) -> Callable[[list[Message]], str]:
    """用 model_adapter.call_llm 造一个摘要函数(侧查询,不影响主对话)。

    失败返回占位文本,不抛异常(避免摘要失败拖垮主流程)。
    """
    async def summarize(to_summarize: list[Message]) -> str:
        try:
            req = ModelRequest(
                messages=[Message(role="system", content=SUMMARY_SYSTEM_PROMPT)] + to_summarize,
                model=getattr(model_adapter, "model", None),
            )
            resp = await model_adapter.call_llm(req)
            return resp.text or ""
        except Exception:
            return "[摘要失败,请基于最近消息继续]"
    return summarize