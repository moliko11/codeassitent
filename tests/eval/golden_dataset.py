"""阶段一 golden dataset(mock 版) -- test-plan §4 五类 case。

每条 case = GoldenCase + 预设脚本(模型该轮返回啥)。ScriptedAdapter 按 input 路由脚本,
单 adapter 跑全 dataset(对齐 test-plan §7.1)。工具走默认 registry 真实执行,故 tool_name
必须真实存在;case 不依赖网络/真实 LLM,尽量不依赖外部文件(只在 code/ 下读项目自身文件)。

运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/eval/test_golden_mock.py -v
    python tests/eval/run_mock.py
"""
from dataclasses import dataclass
from typing import Optional

from agent.adapters.base import BaseModelAdapter
from agent.core.messages import Message
from agent.core.models import ModelResponse
from agent.tools.defs import ToolCall
from agent.tracing.eval import GoldenCase


# ---------- mock adapter ----------

@dataclass
class MockScript:
    """一条 case 的预设响应脚本:按调用顺序返回的 ModelResponse 列表。"""
    responses: list[ModelResponse]


def _tool(call_id: str, tool_name: str, arguments: Optional[dict] = None) -> ModelResponse:
    """造一轮「调工具」的预设响应。"""
    return ModelResponse(
        text=None,
        tool_calls=[ToolCall(call_id=call_id, tool_name=tool_name, arguments=arguments or {})],
    )


def _final(text: str) -> ModelResponse:
    """造一轮「给最终答案」的预设响应(无 tool_calls -> FINISH)。"""
    return ModelResponse(text=text)


class ScriptedAdapter(BaseModelAdapter):
    """按 input 路由预设脚本的 mock adapter。

    scripts: {input_str: [ModelResponse, ...]}。call_llm 取 request 最后一条 user 消息
    作 key,按该 case 已调用次数返回 scripts[key][n]。继承 BaseModelAdapter 获得 stream_llm
    默认实现(退化为 call_llm),故流式路径对 mock 透明。
    """

    def __init__(self, scripts: dict):
        super().__init__(api_key="", base_url="", model="")
        self.scripts = scripts
        self._counters: dict[str, int] = {}

    async def call_llm(self, request):
        key = self._last_user(request)
        n = self._counters.get(key, 0)
        self._counters[key] = n + 1
        return self.scripts[key][n]

    @staticmethod
    def _last_user(request) -> str:
        for m in reversed(getattr(request, "messages", [])):
            if getattr(m, "role", None) == "user":
                return getattr(m, "content", "") or ""
        return ""

    def append_assistant(self, messages, model_response):
        new = list(messages)
        new.append(Message(role="assistant", content=model_response.text or ""))
        return new

    def append_tool_result(self, messages, result):
        new = list(messages)
        new.append(Message(role="tool", content=result.text or ""))
        return new


# ---------- golden dataset(test-plan §4 五类) ----------

# §4.1 工具调用正确性
C_GETNOWTIME = GoldenCase(input="现在几点了", expected_tools=["getnowtime"], expected_answer="时间")
S_GETNOWTIME = MockScript([_tool("c1", "getnowtime"), _final("当前时间是 14:30。")])

C_GLOB = GoldenCase(input="列出 agent 目录下所有 py 文件", expected_tools=["glob"], expected_answer=".py")
S_GLOB = MockScript([
    _tool("c1", "glob", {"pattern": "**/*.py", "path": "agent"}),
    _final("agent 目录下的 py 文件有 agentloop.py、runtime.py 等。"),
])

C_GREP = GoldenCase(input="loop_detector 定义在哪个文件", expected_tools=["grep"], expected_answer="loop_detector")
S_GREP = MockScript([
    _tool("c1", "grep", {"pattern": "class LoopDetector", "path": "agent", "output_mode": "files_with_matches"}),
    _final("loop_detector 定义在 agent/control/loop_detector.py。"),
])

C_READ_OFFSET = GoldenCase(input="读 agentloop.py 的前 50 行", expected_tools=["read"], expected_answer="agentloop")
S_READ_OFFSET = MockScript([
    _tool("c1", "read", {"file_path": "agent/agentloop.py", "offset": 1, "limit": 50}),
    _final("agentloop.py 前 50 行已读取,开头是 import 区。"),
])

# §4.2 上下文治理(先 grep/glob 定位,不全量 read)
C_EXPLORE_PIPE = GoldenCase(input="分析 agent 的工具执行管道", expected_tools=["grep"], expected_answer="execute")
S_EXPLORE_PIPE = MockScript([
    _tool("c1", "grep", {"pattern": "def execute", "path": "agent", "output_mode": "files_with_matches"}),
    _tool("c2", "read", {"file_path": "agent/tools/registry.py", "offset": 1, "limit": 60}),
    _final("工具执行管道在 registry.py 的 execute 方法,含审计/门禁/熔断/retry。"),
])

C_EXPLORE_PROJECT = GoldenCase(input="熟悉一下这个项目结构", expected_tools=["glob"], expected_answer="结构")
S_EXPLORE_PROJECT = MockScript([
    _tool("c1", "glob", {"pattern": "**/*.py", "path": "agent"}),
    _tool("c2", "grep", {"pattern": "class ", "path": "agent", "output_mode": "count"}),
    _final("项目结构已摸清:agent 下分 core/adapters/tools 等模块。"),
])

# §4.3 错误恢复(工具失败后换路 / 止损给 final)
C_READ_MISSING = GoldenCase(input="读 /nope/missing.py 这个文件", expected_tools=["grep"], expected_answer="换")
S_READ_MISSING = MockScript([
    _tool("c1", "read", {"file_path": "/nope/missing.py"}),  # 真实执行 FileNotFoundError
    _tool("c2", "grep", {"pattern": "missing", "path": "agent", "output_mode": "files_with_matches"}),
    _final("该文件不存在,我换成 grep 在项目里搜了一下,没找到。"),
])

C_FAIL_THEN_STOP = GoldenCase(input="查一个不存在的资料", expected_tools=[], expected_answer="没找到")
S_FAIL_THEN_STOP = MockScript([
    _tool("c1", "nonexistent_tool", {"q": "x"}),  # ToolNotFound
    _tool("c2", "nonexistent_tool", {"q": "y"}),  # ToolNotFound
    _final("没找到相关资料。"),
])

# §4.4 终止正确性(常识/问候 -> 直接答,不调工具)
C_ARITH = GoldenCase(input="1+1 等于几", expected_tools=[], expected_answer="2")
S_ARITH = MockScript([_final("1+1 等于 2。")])

C_GREETING = GoldenCase(input="你好", expected_tools=[], expected_answer="你好")
S_GREETING = MockScript([_final("你好!有什么可以帮你的吗?")])

# §4.5 多步任务(查时间 -> 记录到清单)
C_TIME_AND_RECORD = GoldenCase(input="查当前时间并记录到任务清单", expected_tools=["getnowtime", "todo_write"], expected_answer="时间")
S_TIME_AND_RECORD = MockScript([
    _tool("c1", "getnowtime"),
    _tool("c2", "todo_write", {"todos": [{"content": "记录当前时间", "status": "completed", "activeForm": "记录时间"}]}),
    _final("已查到当前时间并记入任务清单。"),
])


# (case, script) 配对,顺序即 Evaluator.run 的结果顺序
MOCK_CASES: list[tuple[GoldenCase, MockScript]] = [
    (C_GETNOWTIME, S_GETNOWTIME),
    (C_GLOB, S_GLOB),
    (C_GREP, S_GREP),
    (C_READ_OFFSET, S_READ_OFFSET),
    (C_EXPLORE_PIPE, S_EXPLORE_PIPE),
    (C_EXPLORE_PROJECT, S_EXPLORE_PROJECT),
    (C_READ_MISSING, S_READ_MISSING),
    (C_FAIL_THEN_STOP, S_FAIL_THEN_STOP),
    (C_ARITH, S_ARITH),
    (C_GREETING, S_GREETING),
    (C_TIME_AND_RECORD, S_TIME_AND_RECORD),
]

# Evaluator.run 用的纯 GoldenCase 列表
MOCK_DATASET: list[GoldenCase] = [c for c, _ in MOCK_CASES]

# ScriptedAdapter 路由表:{input: [responses]}
MOCK_SCRIPTS: dict[str, list[ModelResponse]] = {c.input: s.responses for c, s in MOCK_CASES}


def make_scripted_adapter() -> ScriptedAdapter:
    """造一个按 input 路由的 mock adapter(对齐 test-plan §7.1)。"""
    return ScriptedAdapter(MOCK_SCRIPTS)
