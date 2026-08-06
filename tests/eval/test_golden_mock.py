"""阶段一 mock golden dataset 验收测试。

用 Evaluator 跑 MOCK_DATASET(单 ScriptedAdapter 按 input 路由),对 test-plan §4 五类做精确
断言:工具命中/答案 grounded/状态正确/错误恢复/终止不调工具/多步完成。不依赖真实 LLM。
运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/eval/test_golden_mock.py -v
"""
import os
import sys

import pytest

# 确保 tests/eval/ 在 sys.path(便于 from golden_dataset import)
sys.path.insert(0, os.path.dirname(__file__))

from golden_dataset import (  # noqa: E402
    MOCK_DATASET, make_scripted_adapter,
)
from agent.tools import registry  # noqa: E402
from agent.tracing.eval import Evaluator  # noqa: E402


@pytest.fixture(scope="module")
def results():
    ev = Evaluator(registry)
    return ev.run(MOCK_DATASET, make_scripted_adapter())


def _by_input(results, text):
    for r in results:
        if r.case.input == text:
            return r
    raise KeyError(text)


# §4.1 工具调用正确性:期望工具命中 + 答案 grounded + completed
def test_tool_correctness(results):
    for text in ["现在几点了", "列出 agent 目录下所有 py 文件",
                 "loop_detector 定义在哪个文件", "读 agentloop.py 的前 50 行"]:
        r = _by_input(results, text)
        assert r.tool_accuracy == 1.0, f"{text}: tools={r.actual_tools}"
        assert r.answer_grounded, f"{text}: answer={r.actual_answer!r}"
        assert r.status == "completed", f"{text}: status={r.status}"


# §4.2 上下文治理:先 grep/glob 定位(不全量 read)
def test_context_governance(results):
    r = _by_input(results, "分析 agent 的工具执行管道")
    assert "grep" in r.actual_tools, f"应先用 grep 定位,实际 {r.actual_tools}"
    assert r.status == "completed"
    r2 = _by_input(results, "熟悉一下这个项目结构")
    assert "glob" in r2.actual_tools, f"应先用 glob 摸结构,实际 {r2.actual_tools}"
    assert r2.status == "completed"


# §4.3 错误恢复:工具失败后换路 / 止损给 final(不崩溃)
def test_error_recovery(results):
    r = _by_input(results, "读 /nope/missing.py 这个文件")
    assert "read" in r.actual_tools and "grep" in r.actual_tools, f"应失败后换 grep,实际 {r.actual_tools}"
    assert r.status == "completed", f"恢复后应 completed,实际 {r.status}"
    r2 = _by_input(results, "查一个不存在的资料")
    assert r2.status == "completed", f"止损后应 completed,实际 {r2.status}"
    assert r2.actual_tools, "应确实尝试过工具(失败)"


# §4.4 终止正确性:常识/问候直接答,不调工具
def test_termination(results):
    for text in ["1+1 等于几", "你好"]:
        r = _by_input(results, text)
        assert r.actual_tools == [], f"{text}: 不该调工具,实际 {r.actual_tools}"
        assert r.answer_grounded, f"{text}: answer={r.actual_answer!r}"
        assert r.status == "completed"


# §4.5 多步任务:两步工具都命中 + completed
def test_multistep(results):
    r = _by_input(results, "查当前时间并记录到任务清单")
    assert set(r.actual_tools) == {"getnowtime", "todo_write"}, f"实际 {r.actual_tools}"
    assert r.tool_accuracy == 1.0
    assert r.status == "completed"


# 整体:全部 case 跑通无崩
def test_all_run_without_crash(results):
    assert len(results) == len(MOCK_DATASET)
