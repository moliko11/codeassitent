"""阶段 6 真实 LLM 联调:验证 ContextBuilder 接入 + 三层压缩 + Memory。

跑(3.12 venv,从 code/ 目录):
    python stage6_integration.py

用 deepseek(deepseek-v4-pro)。ark 端点 SSL 超时,不用。
"""
import sys, os, shutil, pathlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 清 __pycache__(避免缓存坑)
[shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]

from agent.config.provider import load_provider_config, make_adapter
from agent.config.config import AgentConfig
from agent.tools.registry import ToolRegistry, ToolExecutor
from agent.tools.defs import Tool, ToolSpec
from agent.memory import MemoryStore
from agent.persist.paths import memory_dir, run_dir
from agent.tools.memory_tool import make_save_memory_tool
from agent.runtime import RuntimeContext
from agent.agentloop import agentloop
from agent.core.state import AgentState
from agent.streaming.sink import NullSink
from agent.core.messages import Message
from agent.context import ContextBuilder

MODEL = "deepseek-v4-pro"  # deepseek 现支持 v4-pro/flash(.env 的 deepseek-chat 是旧名)

# --- 装配 ---
def big_result():
    return "A" * 5000  # 5KB,超 2000 阈值,触发 ToolResultBudget 落盘

reg = ToolRegistry()
reg.register(Tool(
    tool_spec=ToolSpec(name="big_result",
                       description="返回一个大结果(约5KB文本)。调试用。",
                       input_schema={"type": "object", "properties": {}, "required": []}),
    handler=big_result,
))
memory_store = MemoryStore(memory_dir())
reg.register(make_save_memory_tool(memory_store))

pc = load_provider_config("openai_compatible")  # deepseek
adapter = make_adapter(pc)
tool_executor = ToolExecutor(reg)

print(f"=== 阶段 6 联调(deepseek / {MODEL}) ===\n")

# --- 轮1:让模型调 big_result,验证大结果落盘 + ContextBuilder 接入 ---
state = AgentState(max_steps=5)
ctx = RuntimeContext(
    registry=reg, tool_executor=tool_executor, model_adapter=adapter,
    config=AgentConfig(model=MODEL, context_budget=2000),  # 小 budget 触发告警
    state=state, sink=NullSink(), persist=True, memory_store=memory_store,
)
print("--- 轮1:请模型调 big_result ---")
state = agentloop("请调用 big_result 工具,然后简短告诉我返回了多少字符。", ctx)

print("\n=== 轮1 验证 ===")
print("status:", state.status, "| steps:", len(state.steps))
print("tool_history:", [(t.tool_name, t.ok) for t in state.tool_history])
fr = state.final_response
print("final_response:", (fr.text or "")[:120] if fr else None)
# 大结果落盘?
tr_dir = run_dir(state.run_id) / "tool-results"
tr_files = list(tr_dir.iterdir()) if tr_dir.exists() else []
if tr_files:
    print(f"tool-results/ 落盘 {len(tr_files)} 个文件:")
    for f in tr_files:
        print(f"  {f.name}: {f.stat().st_size} 字节(原文 5000)")
else:
    print("tool-results/ 无文件(模型可能没调 big_result)")
# tool 消息是否变引用
for m in state.messages:
    if m.role == "tool":
        c = m.content.get("content", "") if isinstance(m.content, dict) else str(m.content)
        is_ref = c.startswith("<persisted-output>")
        print(f"tool 消息: {'<persisted-output> 引用(已落盘)' if is_ref else '原文'} | 前 50 字符: {c[:50]!r}")

# --- 轮2:让模型 save_memory,验证 memory 写入 ---
state2 = AgentState(max_steps=5, run_id=state.run_id)
state2.messages = state.messages  # 继承上下文
ctx2 = RuntimeContext(
    registry=reg, tool_executor=tool_executor, model_adapter=adapter,
    config=AgentConfig(model=MODEL, context_budget=2000),
    state=state2, sink=NullSink(), persist=True, memory_store=memory_store,
)
print("\n--- 轮2:请模型 save_memory ---")
state2 = agentloop("请记住:我是 Python 开发者,偏好用 Python 写示例代码。", ctx2)

print("\n=== 轮2 验证 ===")
print("status:", state2.status)
print("tool_history:", [(t.tool_name, t.ok) for t in state2.tool_history])
mem_files = os.listdir(memory_store.dir)
print("memory/ 文件:", mem_files)
print("MEMORY.md 索引:\n", memory_store.read_index() or "(空)")

# --- 机制验证:召回注入(不调 LLM,手动 build) ---
print("\n=== 机制验证:召回注入(手动 build) ===")
if not memory_store.list():
    print("memory 为空(模型没 save_memory),手动 write 一个验证召回...")
    memory_store.write("python-pref", "用户偏好 Python", "user",
                       "用户是 Python 开发者,偏好用 Python 写示例。")
test_state = AgentState()
test_state.messages.append(Message(role="system", content="SYS"))
test_state.messages.append(Message(role="user", content="我喜欢什么语言 python"))
builder = ContextBuilder(memory_store=memory_store)
result = builder.build(test_state)
print(f"build 后: messages 数={len(result.messages)} token_count={result.token_count} over_budget={result.over_budget}")
if len(result.messages) > 1 and result.messages[1].role == "system":
    print("messages[1](注入的记忆):")
    print(result.messages[1].content[:400])
else:
    print("未注入(检查 memory_store)")

print("\n=== 联调结束 ===")
