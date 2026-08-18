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
import re
from typing import Callable, Optional

from ..core.messages import Message
from ..core.models import ModelRequest

# 对齐 cc services/compact/prompt.ts 的 BASE_COMPACT_PROMPT(9 段式结构化摘要,中文版)。
# 差异:
#   - cc 前置 NO_TOOLS_PREAMBLE(压缩是 maxTurns=1 的 fork agent,调工具废掉唯一一次机会);
#     本版 summarizer 是纯 call_llm(无 tools),模型不可能调工具,故省略。
#   - cc 用 <analysis> 草稿 + <summary> 剥离,本版同款(format_compact_summary)。
SUMMARY_SYSTEM_PROMPT = (
    "你的任务是把以下对话历史压缩成一份详细摘要,重点保留用户的明确请求和你采取的操作。"
    "这份摘要要足够详尽,能捕捉技术细节、代码模式和架构决策,让后续开发在不丢失上下文的情况下无缝继续。\n"
    "在给出最终摘要前,请先用 <analysis> 标签组织你的分析过程,确保覆盖所有要点。分析时:\n"
    "1. 按时间顺序逐条分析对话的每个部分,对每个部分确认:\n"
    "   - 用户的明确请求和意图\n"
    "   - 你为响应用户请求采取的方法\n"
    "   - 关键决策、技术概念和代码模式\n"
    "   - 具体细节:文件名、完整代码片段、函数签名、文件改动\n"
    "   - 遇到的错误以及如何修复\n"
    "   - 特别留意用户的具体反馈,尤其是用户让你做出不同处理的地方\n"
    "2. 复核技术准确性和完整性,确保每个要素都覆盖到位。\n\n"
    "你的摘要应包含以下章节:\n"
    "1. 主要请求与意图:详细记录用户的所有明确请求和意图\n"
    "2. 关键技术概念:列出讨论过的所有重要技术概念、技术和框架\n"
    "3. 文件与代码片段:枚举查看、修改或创建的具体文件与代码段。特别注意最近的消息,"
    "尽量包含完整代码片段,并说明该文件读取或改动的重要性\n"
    "4. 错误与修复:列出遇到的所有错误以及修复方式。特别注意用户的反馈,"
    "尤其是用户让你做出不同处理的地方\n"
    "5. 问题解决:记录已解决的问题和仍在进行中的排查工作\n"
    "6. 所有用户消息:列出所有非工具结果的用户消息,它们对理解用户反馈和意图变化至关重要\n"
    "7. 待办任务:概述被明确要求继续处理的任务\n"
    "8. 当前工作:精确描述摘要请求之前正在做的事,特别关注最近的消息,包含文件名和代码片段\n"
    "9. 可选下一步:列出与最近工作直接相关的下一步。IMPORTANT:确保该步骤与用户最近的明确请求、"
    "以及你正在进行的任务直接一致。如果上一个任务已结束,只有在你被明确要求时才列出下一步。"
    "如有下一步,请从最近对话中直接引用原文,说明你正在做什么、进行到哪里,防止任务理解漂移。\n\n"
    "输出格式示例:\n"
    "<analysis>\n[你的分析过程,确保所有要点都被准确覆盖]\n</analysis>\n"
    "<summary>\n"
    "1. 主要请求与意图:\n   [详细描述]\n\n"
    "2. 关键技术概念:\n   - [概念 1]\n   - [概念 2]\n\n"
    "3. 文件与代码片段:\n   - [文件名 1]\n      - [重要说明]\n      - [代码片段]\n\n"
    "4. 错误与修复:\n   - [错误描述]:\n      - [修复方式]\n\n"
    "5. 问题解决:\n   [已解决与进行中的排查]\n\n"
    "6. 所有用户消息:\n   - [非工具结果的用户消息]\n\n"
    "7. 待办任务:\n   - [任务 1]\n\n"
    "8. 当前工作:\n   [精确描述]\n\n"
    "9. 可选下一步:\n   [与最近工作直接相关的下一步]\n"
    "</summary>\n\n"
    "请基于以上对话历史生成摘要,严格遵循此结构,确保精确与完整。"
)


def format_compact_summary(text: str) -> str:
    """剥掉 <analysis> 草稿,只留 <summary> 内容(对齐 cc formatCompactSummary)。

    <analysis> 是提高摘要质量的草稿区,一旦摘要写完就没有信息价值,不能进上下文。
    """
    text = re.sub(r"<analysis>[\s\S]*?</analysis>", "", text)
    m = re.search(r"<summary>([\s\S]*?)</summary>", text)
    if m:
        text = m.group(1)
    return text.strip()


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
            return format_compact_summary(resp.text or "")
        except Exception:
            return "[摘要失败,请基于最近消息继续]"
    return summarize