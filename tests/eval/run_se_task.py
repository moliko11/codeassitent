"""自造改 bug 跑 pytest 自验任务 runner(阶段二核心,对标 SWE-bench 迷你版)。

给 agent 一个有 bug 的迷你 Python 项目,让它用 read/grep/edit/bash 修复并跑 pytest 自验。
评测:resolved(pytest pass) / tools_used / self_verified(是否跑 bash 验证) / steps。
真实 LLM(deepseek-v4-pro),本地 venv。从 code/ 运行:
    python tests/eval/run_coding_task.py [task1_off_by_one task2_reverse_words ...]
"""
import os
import sys
import shutil
import tempfile
import subprocess
import asyncio

_HERE = os.path.dirname(__file__)
_CODE = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, _CODE)

from agent.config.provider import load_provider_config, make_adapter
from agent.config.config import AgentConfig
from agent.tools.registry import ToolExecutor
from agent.runtime import RuntimeContext
from agent.agentloop import agentloop
from agent.core.state import AgentState
from agent.streaming.sink import NullSink

TASKS_DIR = os.path.join(_HERE, "se_tasks")
VENV_PY = r"H:\vs_code_file\git-clone-file\agent_leaning\.venv\Scripts\python.exe"
MODEL = "deepseek-v4-pro"


def _stage(name):
    """复制 task 源码+测试到临时目录(排除 task.md/solution.py)。"""
    src = os.path.join(TASKS_DIR, name)
    tmp = tempfile.mkdtemp(prefix=f"coding_{name}_")
    for fn in os.listdir(src):
        if fn in ("task.md", "solution.py"):
            continue
        q=os.path.join(src, fn)
        if os.path.isfile(q): shutil.copy(q, os.path.join(tmp, fn))
    return src, tmp


def _run_pytest(tmp, src):
    """用原始 test 验收(防 agent 改测试作弊),返回 (pass, output)。"""
    shutil.copy(os.path.join(src, "test_source.py"), os.path.join(tmp, "test_source.py"))
    r = subprocess.run([VENV_PY, "-m", "pytest", os.path.join(tmp, "test_source.py"), "-q"],
                       capture_output=True, text=True, timeout=60, cwd=tmp)
    return r.returncode == 0, r.stdout + r.stderr


def _build_registry():
    import agent.tools  # 触发内置工具注册(read/grep/glob/edit/bash/write)
    from agent.tools import registry as reg
    return reg


def run_task(name, max_steps=12):
    src = os.path.join(TASKS_DIR, name)
    with open(os.path.join(src, "task.md"), encoding="utf-8") as f:
        desc = f.read()
    src_dir, tmp = _stage(name)
    test_path = os.path.join(tmp, "test_source.py")
    source_path = os.path.join(tmp, "source.py")
    prompt = (
        f"{desc}\n\n"
        f"项目文件在目录: {tmp}\n"
        f"- 源码: {source_path}\n"
        f"- 测试: {test_path}\n"
        f"请先读源码理解,找出 bug 并用 edit 工具修复 source.py,"
        f"然后用 bash 工具跑测试验证: {VENV_PY} -m pytest {test_path} -q\n"
        f"目标:让所有测试通过。修完并验证通过后,简短说明改了什么。"
    )
    pc = load_provider_config("openai_compatible")
    adapter = make_adapter(pc)
    reg = _build_registry()
    state = AgentState(max_steps=max_steps)
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg), model_adapter=adapter,
        config=AgentConfig(model=MODEL, max_steps=max_steps),
        state=state, sink=NullSink(),
    )
    state = asyncio.run(agentloop(prompt, ctx))
    resolved, pytest_out = _run_pytest(tmp, src)
    tools_used = [h.tool_name for h in state.tool_history]
    result = {
        "task": name, "status": state.status, "resolved": resolved,
        "self_verified": any(h.tool_name == "bash" for h in state.tool_history),
        "steps": len(state.steps), "tools_used": tools_used,
        "final": (state.final_response.text or "")[:200] if state.final_response else "",
        "pytest_tail": pytest_out[-300:],
    }
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def main():
    names = sys.argv[1:] or sorted(d for d in os.listdir(TASKS_DIR) if os.path.isdir(os.path.join(TASKS_DIR, d)))
    print(f"{'task':<24}{'resolved':>9}{'self_ver':>9}{'steps':>7}{'status':>11}  tools")
    print("-" * 92)
    rs = []
    for n in names:
        r = run_task(n)
        rs.append(r)
        print(f"{r['task']:<24}{str(r['resolved']):>9}{str(r['self_verified']):>9}"
              f"{r['steps']:>7}{r['status']:>11}  {r['tools_used']}")
        if not r['resolved']:
            print("  pytest tail: " + r['pytest_tail'][-180:].replace("\n", " | "))
    print("-" * 92)
    print(f"resolved {sum(r['resolved'] for r in rs)}/{len(rs)}  "
          f"self_verified {sum(r['self_verified'] for r in rs)}/{len(rs)}")


if __name__ == "__main__":
    main()
