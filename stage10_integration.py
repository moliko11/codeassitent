"""阶段10 真实 LLM 联调:验证多 Agent handoff 链(orchestrator -> search -> coder -> reviewer)。

跑(3.12 venv,从 code/ 目录,需 .env 配 DEEPSEEK_API_KEY/BASE_URL/MODEL):
    python stage10_integration.py

用 deepseek(deepseek-v4-pro)。验证:orchestrator 调 handoff 工具 -> detect_handoff 解析 ->
worker 跑 -> blackboard 回灌 -> 多 worker 串行链 -> trace span agent_id 看流转。

设计:registry 只注册 handoff(orchestrator allowed_tools=["handoff"] 只能 handoff 或 FINISH;
worker tools=[] 看不到 handoff,纯 LLM 作答),不依赖外部工具/key,聚焦 handoff 机制本身。
"""
import sys, os, shutil, pathlib, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 清 __pycache__(Windows mtime 缓存坑,见 CLAUDE.md)
[shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]
# Windows 默认 stdout 是 GBK,编码不了 LLM 输出里的 emoji/符号;切 UTF-8(失败也不影响,printer 有兜底)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from agent.config.provider import load_provider_config, make_adapter
from agent.config.config import AgentConfig
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.runtime import RuntimeContext
from agent.streaming.printer import StreamingPrinter
from agent.streaming.sink import CompositeSink
from agent.tracing import Tracer
from agent.core.state import AgentState
from agent.multiagent import OrchestratorAgent, WorkerAgent, Blackboard

MODEL = "deepseek-v4-pro"

ORCH_PROMPT = """你是一个多 Agent 协作的 orchestrator(协调者)。你不直接做事,而是通过 handoff 工具把子任务委派给专职 worker,收集结果后给出最终答案。

## 可用 worker(用 handoff 工具委派,to_role 填角色名)
- search:调查/搜索 worker,擅长查资料、整理信息。
- coder:代码 worker,擅长写代码、给示例。
- reviewer:审查 worker,擅长评估代码/方案质量。

## 工作方式(重要)
- 每轮只 handoff 一个 worker:调用 handoff 工具(to_role + context),然后**结束本轮**(下一条回复只输出简短文本如"已委派 search",不要附带任何 tool_calls)。
- 下一轮你会看到该 worker 的结果已写入 blackboard(共享黑板)。基于它决定:继续 handoff 下一个 worker,还是收尾。
- 所有子任务完成时,输出最终总结(只文本,无 tool_calls)。

## 终止约定
- 想结束本轮/对话:只输出文本,不要 tool_calls。
- 要委派:返回 handoff tool_call(to_role + context)。"""

SEARCH_PROMPT = "你是 search worker,擅长调查/整理信息。基于任务和共享黑板里的已有信息,给出简洁的调查结果。完成后只输出文本(不要 tool_calls)。"
CODER_PROMPT = "你是 coder worker,擅长写代码。基于任务和共享黑板里的调查结果,写出代码或示例。完成后只输出文本(不要 tool_calls)。"
REVIEWER_PROMPT = "你是 reviewer worker,擅长审查。基于任务和共享黑板里的代码/方案,给出审查意见(是否正确、有何改进)。完成后只输出文本(不要 tool_calls)。"

# --- 装配 ---
pc = load_provider_config("openai_compatible")  # deepseek
if not pc.api_key:
    raise SystemExit("未设置 DEEPSEEK_API_KEY,请在 code/.env 配置 DEEPSEEK_API_KEY/BASE_URL/MODEL")
adapter = make_adapter(pc)

reg = ToolRegistry()  # 空;orchestrator __init__ 注册 handoff(worker 看不到它)
tool_executor = ToolExecutor(reg)
tracer = Tracer("stage10_integration")  # 内存 trace(看 span agent_id 流转)
sink = CompositeSink(StreamingPrinter(), tracer)

rt = RuntimeContext(
    registry=reg, tool_executor=tool_executor, model_adapter=adapter,
    config=AgentConfig(model=MODEL, max_steps=8),
    state=AgentState(), sink=sink, persist=False,
)

# 三个 worker(各自 config + system_prompt + tools=[];registry 只有 handoff,worker 看不到,纯 LLM)
search = WorkerAgent(role="search", tools=[],
    config=AgentConfig(model=MODEL, system_prompt=SEARCH_PROMPT, max_steps=4), runtime=rt)
coder = WorkerAgent(role="coder", tools=[],
    config=AgentConfig(model=MODEL, system_prompt=CODER_PROMPT, max_steps=4), runtime=rt)
reviewer = WorkerAgent(role="reviewer", tools=[],
    config=AgentConfig(model=MODEL, system_prompt=REVIEWER_PROMPT, max_steps=4), runtime=rt)
orch = OrchestratorAgent(runtime=rt, workers=[search, coder, reviewer], max_handoffs=6,
    config=AgentConfig(model=MODEL, system_prompt=ORCH_PROMPT, max_steps=8))

TASK = ("请用三个 worker 协作完成:1) 用 search worker 调查 Python 3.12 的主要新特性;"
        "2) 用 coder worker 基于调查写一段 3 行内的示例代码;"
        "3) 用 reviewer worker 审查示例代码是否正确。每步用 handoff 委派对应 worker。")

print(f"=== 阶段 10 联调(deepseek / {MODEL})===\n")
print(f"任务: {TASK}\n")

bb = Blackboard()
state = asyncio.run(orch.run(TASK, bb))

print("\n" + "=" * 60)
print("=== 联调结果 ===")
print("status:", state.status)
fr = state.final_response
print("final_response:", (fr.text or "")[:500] if fr else None)
print("\n--- blackboard(worker 结果回灌)---")
print(bb.snapshot() or "(空)")
print("\n--- handoff_history(orchestrator 的委派记录)---")
print(orch.handoff_history or "(无 handoff - orchestrator 可能直接答了)")
print("\n--- trace 树(span agent_id 看 agent 间流转)---")
print(tracer.trace.to_tree())
print("\n=== 联调结束 ===")
