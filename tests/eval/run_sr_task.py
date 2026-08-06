"""search-and-replace 能力评测 runner。

给 agent 多文件 codebase + 修改意图,评估:
- search: agent 改的文件是否命中 gold_locations(定位对文件?)
- replace: edit 后 pytest 是否 pass(改对?)
- 效率: 步数/tools
真实 LLM(deepseek-v4-pro)。从 code/ 运行:
    python tests/eval/run_sr_task.py [sr_task1_calc sr_task2_blog]
"""
import os, sys, shutil, tempfile, subprocess, asyncio, hashlib, json

_HERE = os.path.dirname(__file__)
_CODE = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE); sys.path.insert(0, _CODE)

from agent.config.provider import load_provider_config, make_adapter
from agent.config.config import AgentConfig
from agent.tools.registry import ToolExecutor
from agent.runtime import RuntimeContext
from agent.agentloop import agentloop
from agent.core.state import AgentState
from agent.streaming.sink import NullSink

TASKS_DIR = os.path.join(_HERE, "sr_tasks")
VENV_PY = r"H:\vs_code_file\git-clone-file\agent_leaning\.venv\Scripts\python.exe"
MODEL = "deepseek-v4-pro"


def _hash_files(d):
    h = {}
    for root, _, files in os.walk(d):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".pyc"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            with open(p, "rb") as fh:
                h[rel] = hashlib.md5(fh.read()).hexdigest()
    return h


def _stage(name):
    src = os.path.join(TASKS_DIR, name)
    cb = os.path.join(src, "codebase")
    tmp = tempfile.mkdtemp(prefix=f"sr_{name}_")
    for root, _, files in os.walk(cb):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, cb)
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(p, dst)
    return src, tmp


def _restore_tests(src, tmp):
    cb = os.path.join(src, "codebase")
    for root, _, files in os.walk(cb):
        for f in files:
            if f.startswith("test_") and f.endswith(".py"):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, cb)
                shutil.copy(p, os.path.join(tmp, rel))


def _run_pytest(tmp):
    tests = [os.path.join(r, f) for r, _, fs in os.walk(tmp)
             for f in fs if f.startswith("test_") and f.endswith(".py")]
    if not tests:
        return False, "no tests"
    r = subprocess.run([VENV_PY, "-m", "pytest", *tests, "-q"],
                       capture_output=True, text=True, timeout=60, cwd=tmp)
    return r.returncode == 0, r.stdout + r.stderr


def _build_registry():
    import agent.tools
    from agent.tools import registry as reg
    return reg


def run_task(name, max_steps=12):
    src = os.path.join(TASKS_DIR, name)
    with open(os.path.join(src, "instruction.md"), encoding="utf-8") as f:
        instr = f.read()
    gold = json.load(open(os.path.join(src, "gold_locations.json"), encoding="utf-8"))
    src_dir, tmp = _stage(name)
    before = _hash_files(tmp)
    prompt = (
        f"{instr}\n\n"
        f"项目在目录: {tmp}\n"
        f"请用 read/grep/glob 探索代码定位,用 edit 修复,"
        f"然后用 bash 跑测试验证: {VENV_PY} -m pytest {tmp} -q\n"
        f"目标:让所有测试通过。完成后简短说明改了哪个文件、改了什么。"
    )
    pc = load_provider_config("openai_compatible")
    adapter = make_adapter(pc)
    reg = _build_registry()
    state = AgentState(max_steps=max_steps)
    ctx = RuntimeContext(
        registry=reg, tool_executor=ToolExecutor(reg), model_adapter=adapter,
        config=AgentConfig(model=MODEL, max_steps=max_steps),
        state=state, sink=NullSink())
    state = asyncio.run(agentloop(prompt, ctx))
    after = _hash_files(tmp)
    changed = [rel for rel in after if before.get(rel) != after[rel]]
    search_hit = gold["file"] in changed
    _restore_tests(src, tmp)
    func_correct, pytest_out = _run_pytest(tmp)
    tools_used = [h.tool_name for h in state.tool_history]
    result = {
        "task": name, "status": state.status,
        "search_hit": search_hit, "changed_files": changed,
        "gold_file": gold["file"], "gold_func": gold.get("function", ""),
        "replace_correct": func_correct,
        "tools_used": tools_used, "steps": len(state.steps),
        "tool_calls": [(tc.tool_name, tc.arguments) for s in state.steps if s.model_response for tc in (s.model_response.tool_calls or [])],
        "final": (state.final_response.text or "")[:200] if state.final_response else "",
        "pytest_tail": pytest_out[-200:] if isinstance(pytest_out, str) else "",
    }
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def main():
    names = sys.argv[1:] or ["sr_task1_calc", "sr_task2_blog"]
    print(f"{'task':<20}{'search':>8}{'replace':>9}{'steps':>7}{'status':>11}  changed")
    print("-" * 88)
    rs = []
    for n in names:
        r = run_task(n)
        rs.append(r)
        print(f"{r['task']:<20}{str(r['search_hit']):>8}{str(r['replace_correct']):>9}"
              f"{r['steps']:>7}{r['status']:>11}  {r['changed_files']}")
        print('    tool_calls:', r['tool_calls'])
        if not r['replace_correct']:
            print("  pytest: " + r['pytest_tail'][-150:].replace("\n", " | "))
    print("-" * 88)
    print(f"search_hit {sum(r['search_hit'] for r in rs)}/{len(rs)}  "
          f"replace {sum(r['replace_correct'] for r in rs)}/{len(rs)}")


if __name__ == "__main__":
    main()
