"""阶段 6 步骤 6 测试:Memory(MEMORY.md 索引 + memory 文件 + save_memory + build 分层注入)。

不依赖真实 LLM。运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_memory.py -v
"""
import pytest
from agent.memory import MemoryStore, MEMORY_TYPES
from agent.tools.memory_tool import make_save_memory_tool
from agent.context import ContextBuilder
from agent.core.messages import Message
from agent.core.state import AgentState


def test_write_creates_md_and_updates_index(tmp_path):
    """write 两步:写 md 文件 + 更新 MEMORY.md 索引(对齐 cc)。"""
    store = MemoryStore(tmp_path)
    store.write(name="python-pref", description="用户偏好 Python",
                type="user", content="用户用 Python 写后端")
    # md 文件
    r = store.read("python-pref")
    assert r.type == "user" and "Python" in r.content
    # MEMORY.md 索引有该行
    idx = store.read_index()
    assert "python-pref.md" in idx and "用户偏好 Python" in idx


def test_write_updates_existing_no_duplicate(tmp_path):
    """同名 write 更新 description,索引不重复(对齐 cc:不写重复)。"""
    store = MemoryStore(tmp_path)
    store.write("a", "旧描述", "user", "ca")
    store.write("a", "新描述", "user", "ca2")
    idx = store.read_index()
    assert idx.count("](a.md)") == 1  # 只一行
    assert "新描述" in idx and "旧描述" not in idx


def test_write_rejects_bad_type(tmp_path):
    store = MemoryStore(tmp_path)
    with pytest.raises(ValueError):
        store.write(name="x", description="d", type="bad", content="c")


def test_forget_removes_md_and_index(tmp_path):
    """forget 删 md + 从索引移除该行。"""
    store = MemoryStore(tmp_path)
    store.write("a", "da", "user", "ca")
    store.write("b", "db", "project", "cb")
    assert store.forget("a") is True
    assert store.forget("missing") is False
    idx = store.read_index()
    assert "a.md" not in idx and "b.md" in idx
    assert len(store.list()) == 1


def test_recall_keyword_match(tmp_path):
    """recall 按 query 关键词匹配正文,命中的返回,不命中的不返回。"""
    store = MemoryStore(tmp_path)
    store.write("python-pref", "用户偏好 Python", "user", "用户用 Python 写后端")
    store.write("go-pref", "用户偏好 Go", "user", "用户用 Go 写微服务")
    out = store.recall("用什么语言写后端 python", top_k=5)
    names = [r.name for r in out]
    assert "python-pref" in names
    assert "go-pref" not in names


def test_recall_empty_when_no_match(tmp_path):
    store = MemoryStore(tmp_path)
    store.write("a", "da", "user", "ca")
    assert store.recall("完全无关xyz", top_k=5) == []


def test_save_memory_tool_writes_store_and_index(tmp_path):
    """save_memory 工具调用后:md 文件 + MEMORY.md 索引都更新。"""
    store = MemoryStore(tmp_path)
    tool = make_save_memory_tool(store)
    result = tool.handler(name="feedback-terse", description="用户要简洁回答",
                          type="feedback", content="用户不喜欢冗长总结")
    assert result["ok"] is True
    r = store.read("feedback-terse")
    assert r.type == "feedback" and "冗长" in r.content
    assert "feedback-terse.md" in store.read_index()


def test_build_injects_index_and_recall(tmp_path):
    """集成:build 注入 MEMORY.md 索引(常驻)+ 召回正文(按需)。"""
    store = MemoryStore(tmp_path)
    store.write("python-pref", "用户偏好 Python", "user", "用户用 Python 写后端")
    state = AgentState()
    state.messages.append(Message(role="system", content="SYS"))
    state.messages.append(Message(role="user", content="用什么语言写后端 python"))
    builder = ContextBuilder(memory_store=store)
    result = builder.build(state)
    # system 之后插了一条记忆 system 消息
    injected = result.messages[1]
    assert injected.role == "system"
    content = injected.content
    assert "记忆索引" in content and "python-pref.md" in content  # 索引
    assert "召回的相关记忆" in content and "Python 写后端" in content  # 正文
    # 不改 state.messages
    assert len(state.messages) == 2


def test_build_injects_index_only_when_no_recall_match(tmp_path):
    """recall 无命中时,仍注入索引(常驻)。"""
    store = MemoryStore(tmp_path)
    store.write("a", "da", "user", "ca")
    state = AgentState()
    state.messages.append(Message(role="user", content="完全无关xyz"))
    builder = ContextBuilder(memory_store=store)
    result = builder.build(state)
    injected = result.messages[0]
    assert "记忆索引" in injected.content
    assert "召回的相关记忆" not in injected.content  # 无命中


def test_build_no_inject_when_no_memory(tmp_path):
    """无 memory 文件时不注入(不插空记忆)。"""
    store = MemoryStore(tmp_path)  # 空目录
    state = AgentState()
    state.messages.append(Message(role="user", content="hi"))
    builder = ContextBuilder(memory_store=store)
    result = builder.build(state)
    assert len(result.messages) == len(state.messages)