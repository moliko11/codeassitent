# 第 1 层压缩:ToolResultBudget -- 超大工具结果落盘,messages 放引用(无损)
#
# 对齐 cc utils/toolResultStorage.ts 的 applyToolResultBudget / enforceToolResultBudget:
#   - 不截断(信息无损),全文写磁盘,messages 放 <persisted-output> 引用
#   - 模型需要全文时,用文件读取工具按 path 读回
#
# 与 cc 的简化差异(见文件末"已知简化"):
#   - cc 按"每条 message 的总 budget"选最大的几个落盘;本版按"单结果超阈值"落盘(更直接)
#   - cc 用 ContentReplacementState 跨轮记忆避免重复处理;本版靠"文件已存在则跳过"幂等
#   - cc 对 Read 类工具(maxResultSizeChars=Infinity)永不落盘防循环;本版未区分
#
# 关键约定:不改 state.messages 原始对象。返回新 list + 新 Message,原始历史保持完整
# (对应 cc 的 messages vs messagesForQuery 区分:state.messages 是完整历史,
#  build 返回的才是发给模型的裁剪版)。
from pathlib import Path

from ..core.messages import Message
from ..persist.paths import tool_results_dir

PERSIST_THRESHOLD_CHARS = 2000   # 单个工具结果超此字符数 -> 落盘
PREVIEW_CHARS = 500              # 引用里的预览长度

PERSISTED_TAG = "<persisted-output>"
PERSISTED_CLOSE_TAG = "</persisted-output>"


def _is_tool_result(msg: Message) -> bool:
    """识别 role=tool 的消息(OpenAI 兼容格式:content 是 dict,含 tool_call_id + content)。

    对齐 adapters/openai_compat.py 的 append_tool_result 产出的格式。
    test_smoke 的 _ScriptedAdapter 用字符串 content(非 dict),不会被识别--真实 adapter 才走这条路径。
    """
    return (
        msg.role == "tool"
        and isinstance(msg.content, dict)
        and "tool_call_id" in msg.content
        and "content" in msg.content
    )


def _persist(run_id: str, call_id: str, text: str) -> Path:
    """把完整结果写到 tool-results/<call_id>.txt,返回路径。幂等:已存在则跳过。"""
    path = tool_results_dir(run_id) / f"{call_id}.txt"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path


def _build_reference(path: Path, full_text: str) -> str:
    """生成存盘引用:预览 + 路径 + 全文长度。"""
    preview = full_text[:PREVIEW_CHARS]
    return (
        f"{PERSISTED_TAG}\n"
        f"path: {path}\n"
        f"{preview}\n"
        f"(全文共 {len(full_text)} 字符已存盘,可用文件读取工具按 path 读回)\n"
        f"{PERSISTED_CLOSE_TAG}"
    )


def apply_tool_result_budget(
    messages: list[Message],
    run_id: str,
    threshold: int = PERSIST_THRESHOLD_CHARS,
) -> list[Message]:
    """第 1 层压缩:超大工具结果落盘,messages 里换成引用(无损)。

    遍历 messages,对超阈值的 tool_result:落盘 + 新建 Message(content 的 "content" 换成引用)。
    其余原样保留。不修改入参的 Message 对象。
    """
    out: list[Message] = []
    for msg in messages:
        if not _is_tool_result(msg):
            out.append(msg)
            continue
        text = msg.content["content"]
        if not isinstance(text, str) or len(text) <= threshold:
            out.append(msg)
            continue
        call_id = msg.content["tool_call_id"]
        path = _persist(run_id, call_id, text)
        ref = _build_reference(path, text)
        # 新建 Message(不动原对象):content dict 浅拷贝,"content" 换成引用
        new_content = dict(msg.content)
        new_content["content"] = ref
        out.append(Message(role=msg.role, content=new_content, meta=msg.meta))
    return out