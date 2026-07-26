# token 近似计数 —— 阶段 6 任务 2(context_budget 的度量基础)
#
# 为什么是"近似"：精确计数需要 provider 专用 tokenizer(OpenAI 用 tiktoken，
# 豆包/DeepSeek 各自不同)，引入依赖且未必对得上 provider 实际计费。
# 学习阶段先用字符近似跑通机制；进阶可换成 adapter.count_tokens 或 tiktoken，
# 接口(count_message_tokens)不变，只换实现。
#
# 近似规则(经验值)：
#   - 英文 ~4 字符/token
#   - 中文 ~1.5 字符/token(一个汉字约 1~2 token)
# 混合文本按 Unicode 码点区分后分别估算。
import json

from ..core.messages import Message


def estimate_text_tokens(text) -> int:
    """单段文本的 token 近似值。None/空 -> 0。非字符串先 json 序列化。"""
    if not text:
        return 0
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    # 中文 ~1.5 字符/token，英文 ~4 字符/token，+1 容纳边界开销
    return int(cjk / 1.5) + int(other / 4) + 1


def count_message_tokens(messages: list[Message]) -> int:
    """整条对话的 token 近似总数。

    每条 message = role/结构固定开销(4) + content token。
    对齐 cc：这只是估算，真实以 provider 返回的 usage.input_tokens 为准。
    """
    total = 0
    for m in messages:
        total += 4  # role + 包裹结构的固定开销(OpenAI 经验值)
        content = m.content
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            # RichMessage 风格的多 ContentBlock(阶段 6 暂未启用，预留)
            for block in content:
                data = getattr(block, "data", block)
                total += estimate_text_tokens(
                    data if isinstance(data, str)
                    else json.dumps(data, ensure_ascii=False)
                )
        else:
            total += estimate_text_tokens(content)
    return total