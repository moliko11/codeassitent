# ContextBuilder —— 调 LLM 前组装 messages 的入口(阶段 6 地基)
#
# 设计目标：把"组装给模型的 messages"从 agentloop 里抽出来。agentloop 只管
# "拿 messages -> 调模型 -> 处理 action"，"messages 怎么来"归 ContextBuilder。
# 这样后续 SlidingWindow/Summarize/工具结果降级/memory 投影都改 build()，主循环不动。
#
# 对齐 cc：cc 在调 LLM 前过 snip->microcompact->autocompact 管线；本阶段 build()
# 只做"透传 + 计数 + budget 检查"，是那条管线的空壳。
from dataclasses import dataclass
from typing import Callable, Optional

from ..core.messages import Message
from ..core.state import AgentState
from typing import Callable, Optional, TYPE_CHECKING

from .auto_compact import auto_compact
from .budget import apply_tool_result_budget
from .counter import count_message_tokens
from .micro_compact import micro_compact

if TYPE_CHECKING:
    from ..memory.store import MemoryStore

@dataclass
class BuildResult:
    """build() 的返回：组装后的 messages + 本次统计(供调试/tracing)。"""
    messages: list[Message]
    token_count: int            # 组装后的 token 近似数
    budget: Optional[int]       # 本次使用的 budget(None=不限)允许使用的 Token 预算上限
    over_budget: bool           # 是否超 budget(本阶段只标记，不裁剪) 标记当前构建后的消息 是否已超出预算


class ContextBuilder:
    """组装发给模型的 messages。

    当前(阶段 6 地基)：透传 state.messages + token 计数 + budget 检查。
    后续在此挂载：SlidingWindowStrategy / SummarizeStrategy / 工具结果降级 / memory 召回投影。

    注意：build() 内部对 state.messages 做浅拷贝(list(...))，后续裁剪策略改的是
    这个副本，不会动到 state.messages 原始 list。但 Message 对象本身是共享的——
    策略若要改某条 Message，应新建 Message 对象，不要原地改(避免污染 state 与 transcript)。
    """

    def __init__(
        self,
        context_budget: Optional[int] = None,
        warn_sink: Optional[Callable[[str], None]] = None,
        tool_result_threshold: int = 2000,
        keep_recent: int = 3,
        summarizer: Optional[Callable[[list], str]] = None,
        keep_recent_turns: int = 4,
        memory_store: "MemoryStore | None" = None,
        memory_recall_top_k: int = 3,
    ):
        """
        :param context_budget: 单次请求输入侧 token 预算上限(None=不限制)。
            注意是"输入侧"预算，要给 output 留余量：模型 context window 减去
            max_tokens 再打折，例如 32k window - 5k output -> budget ~ 24000。
        :param warn_sink: 超 budget 时的告警回调(如 print 到 stderr)。
            本阶段不裁剪，只告警，方便观察"何时该上 SlidingWindow"。
        :param tool_result_threshold 
        """
        self.context_budget = context_budget
        self.warn_sink = warn_sink
        self.tool_result_threshold = tool_result_threshold  # 步3:超此字符的工具结果落盘
        self.keep_recent = keep_recent                      # 步4:保留最近 K 个 tool_result 原文
        self.summarizer = summarizer                        # 步5:超 budget 时的摘要函数(None=不摘要)
        self.keep_recent_turns = keep_recent_turns          # 步5:摘要时保留尾部 N 条
        self.memory_store = memory_store                    # 步6:长期记忆(None=不召回)
        self.memory_recall_top_k = memory_recall_top_k      # 步6:召回 top_k(context.yaml,缺省 3)

    async def build(self, state: AgentState) -> BuildResult:
        """从 state 组装发给模型的 messages。

        当前实现：透传 state.messages(不动)，只做计数 + budget 检查。
        行为和原来 agentloop 直接用 state.messages 完全一致，只是把组装显式化了。
        """
        messages = list(state.messages)  # 浅拷贝:策略改副本,不动 state 原始 list
        # 阶段7:plan_execute 模式,注入"当前子任务"system 提示(聚焦当前 plan step,防模型跳步)
        current_plan_step = state.meta.get("current_plan_step")
        if current_plan_step:
            messages = [Message(role="system",
                content=f"[当前子任务]{current_plan_step}\n聚焦完成它,不要跳到其他任务。")] + messages
        # 步3 第1层(无损):超大工具结果落盘,messages 换引用
        messages = apply_tool_result_budget(messages, state.run_id, self.tool_result_threshold)
        # 步4 第3层(低损):清老 tool_result content 成占位
        messages = micro_compact(messages, self.keep_recent)
        token_count = count_message_tokens(messages)
        budget = self.context_budget
        over = budget is not None and token_count > budget
        # 步5 第5层(有损兜底):前两层压不下才摘要
        if over and self.summarizer is not None:
            messages = await auto_compact(messages, self.summarizer, self.keep_recent_turns)
            token_count = count_message_tokens(messages)
            over = budget is not None and token_count > budget

        # 步6:memory 分层注入(索引常驻 + 召回全文,不改 state.messages)
        if self.memory_store is not None:
            messages = self._inject_memory(messages)
            token_count = count_message_tokens(messages)
            over = budget is not None and token_count > budget

        if over and self.warn_sink is not None:
            # 本阶段只告警不裁剪。下一块 SlidingWindow：over 时丢老消息/摘要替换。
            try:
                self.warn_sink(
                    f"[ContextBuilder] over budget: {token_count} > {budget} "
                    f"(messages={len(messages)})"
                )
            except Exception:
                pass  # 告警失败不影响主流程

        return BuildResult(
            messages=messages,
            token_count=token_count,
            budget=budget,
            over_budget=over,
        )


    def _last_user_text(self, messages: list) -> str | None:
        """取最后一条 user 消息文本,作 recall 的 query。"""
        for m in reversed(messages):
            if m.role == "user":
                c = m.content
                return c if isinstance(c, str) else str(c)
        return None

    def _inject_memory(self, messages: list) -> list:
        """分层注入(对齐 cc):MEMORY.md 索引常驻(轻)+ recall 召回全文(重)。

        合并成一条 system 消息插在头部(system 之后)。不改入参。
        """
        parts = []
        # 1. 索引常驻(对齐 cc:MEMORY.md 始终在系统提示)
        index = self.memory_store.read_index()
        if index.strip():
            parts.append("[记忆索引(MEMORY.md)]\n" + index.strip())
        # 2. 召回全文(按需,对齐 cc findRelevantMemories)
        query = self._last_user_text(messages)
        if query:
            recalled = self.memory_store.recall(query, top_k=self.memory_recall_top_k)
            if recalled:
                rec_text = "\n\n".join(
                    f"## {r.name}({r.type})\n{r.description}\n\n{r.content}"
                    for r in recalled
                )
                parts.append("[召回的相关记忆]\n" + rec_text)
        if not parts:
            return messages
        mem_text = "\n\n".join(parts)
        insert_at = 1 if (messages and messages[0].role == "system") else 0
        return messages[:insert_at] + [Message(role="system", content=mem_text)] + messages[insert_at:]