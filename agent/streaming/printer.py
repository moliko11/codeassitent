# 流式渲染器：把 EventSink 事件渲染成 claude-code 风格的终端输出。REPL 用。
#
# 渲染策略（最小而有效）：
# - TextDelta：不换行逐字输出 + flush -> 打字机效果（这是「流式」体验的核心）
# - ToolStart：换行 + 缩进打印 ⏺ name(参数摘要)  -- 工具开始执行
# - ToolEnd：  缩进打印 ⎿ ok/fail 摘要 (耗时)    -- 工具执行完
# - RunEnd：   收尾换行；非 completed 给状态提示
# - 其余事件（RunStart/StepStart/StepEnd/ToolCall*/MessageEnd）默认不渲染：
#   它们是「机制」事件，用户可见信息已被上面三类覆盖。
#   想看模型工具参数增量流（ToolCallDelta）可在此展开（verbose 模式）。
import sys
from typing import Any, TextIO

from .sink import EventSink
from .events import TextDelta, ThinkingDelta, ToolStart, ToolEnd, RunEnd
from ..tools import _runtime_state

# ANSI 颜色（Win10+ 原生支持；use_color=False 时降级为纯文本，避免乱码）
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _args_brief(arguments: dict[str, Any]) -> str:
    """工具参数一句话摘要：取前 3 个 key=value，长值截断。"""
    if not arguments:
        return ""
    parts = []
    for k, v in list(arguments.items())[:3]:
        s = str(v)
        if len(s) > 40:
            s = s[:40] + "…"
        parts.append(f"{k}={s}")
    return ", ".join(parts)


class StreamingPrinter(EventSink):
    """把流式事件渲染到终端。

    用法：作为 RuntimeContext.sink 传入；agentloop 运行时事件实时打印。
    """

    def __init__(self, out: TextIO | None = None, use_color: bool = True,
                 expose_reasoning: bool = True):
        self.out = out or sys.stdout
        self.use_color = use_color
        self.expose_reasoning = expose_reasoning  # 阶段7:False 时隐藏 ThinkingDelta(内部 CoT),最终回答不受影响
        self._in_text = False  # 是否正处在逐字文本输出中（ToolStart/RunEnd 前需补换行）

    def _c(self, code: str, s: str) -> str:
        return f"{code}{s}{_RESET}" if self.use_color else s

    def _write(self, s: str) -> None:
        try:
            self.out.write(s)
        except UnicodeEncodeError:
            # 流无法编码某些字符（如 Windows GBK stdout 遇到 ⏺/⎿）。
            # 用流自身编码做 replace（GBK 仍能编码中文，只替换符号），尽量保留内容；
            # 仍失败则退化为 ASCII（丢非 ASCII 但保证不崩）。
            enc = getattr(self.out, "encoding", None) or "utf-8"
            try:
                self.out.write(s.encode(enc, "replace").decode(enc, "replace"))
            except (UnicodeEncodeError, LookupError):
                self.out.write(s.encode("ascii", "replace").decode("ascii"))

    def _ensure_newline(self) -> None:
        """文本流中收到工具/结束事件时，先收尾换行。"""
        if self._in_text:
            self._write("\n")
            self._in_text = False

    def emit(self, event) -> None:
        # 子 agent 事件不渲染到主终端(REPL):Agent.run 设了 _runtime_state.agent_id(role),
        # 主 agent/单 agent 是 None。子 agent 工具过程只在后台跑,结果经 tool_result/[task-notification]
        # 回灌主 agent;若在这里打印会混入主 REPL 输出、甚至撞 `User: ` prompt(曾实测 `User:   ⎿ ok {...}`)。
        # sink 链路保留,故 trace/SSE 仍收到子 agent 事件(带 agent_id,供监控/web 展示)。
        if _runtime_state.agent_id.get() is not None:
            return
        match event:
            case TextDelta(text):
                # 不换行逐字输出 -> 打字机效果（最终回答,始终可见,不受 expose_reasoning 影响）
                self._write(text)
                self.out.flush()
                self._in_text = True

            case ThinkingDelta(text):
                # 模型内部 CoT:expose_reasoning=False 时隐藏（对齐 CC）;True 时用 dim 灰色区分正文
                if not self.expose_reasoning:
                    return
                self._write(self._c(_DIM, text))
                self.out.flush()
                self._in_text = True

            case ToolStart(_, tool_name, arguments):
                self._ensure_newline()
                brief = _args_brief(arguments)
                line = f"  ⏺ {tool_name}({brief})"
                self._write(self._c(_CYAN, line) + "\n")

            case ToolEnd(_, tool_name, ok, elapsed_ms, error_type, summary):
                if ok:
                    tag = self._c(_GREEN, "ok")
                else:
                    tag = self._c(_RED, f"fail({error_type or 'error'})")
                tail = f" ({elapsed_ms:.0f}ms)" if elapsed_ms else ""
                summ = f" {summary}" if summary else ""
                self._write(self._c(_DIM, f"  ⎿ {tag}{tail}{summ}") + "\n")

            case RunEnd(status, final_text, error):
                self._ensure_newline()
                if status != "completed":
                    msg = (error or {}).get("message", "") if error else ""
                    line = f"  [run {status}] {msg}".rstrip()
                    self._write(self._c(_YELLOW, line) + "\n")

            case _:
                # RunStart / StepStart / StepEnd / ToolCallStart/Delta/End / MessageEnd：默认不渲染
                pass
