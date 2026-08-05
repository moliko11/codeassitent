"""工具体系测试(步 1+2)。运行(从 code/ 目录,3.12 venv):
    python -m pytest tests/test_tools.py -v

不依赖真实 LLM。fileHistory 是纯 stdlib 底座,直接构造测;
工具测试直接调 tool.handler(...)(不经 executor,快);备份联动测试走 ToolExecutor + before_mutation。
"""
import asyncio
import os
import time

import pytest

from agent.utils.fileHistory import FileHistory, INITIAL_STEP_ID, MAX_SNAPSHOTS
from agent.tools import _runtime_state
from agent.tools.registry import registry, ToolExecutor
from agent.tools.defs import ToolCall
from agent.adapters.base import BaseModelAdapter
from agent.core.models import ModelResponse
from agent.core.messages import Message
from agent.agentloop import agentloop, _track_edit_callback
from agent.runtime import RuntimeContext
from agent.config.config import AgentConfig
from agent.core.state import AgentState


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    """每测试重置 _runtime_state(模块级全局,防测试间残留)。"""
    _runtime_state.reset()
    yield
    _runtime_state.reset()


def _tool(name):
    """从默认 registry 拿工具(快捷调 handler)。"""
    return registry.get_tool(name)


# ============ fileHistory 底座 ============

def test_track_edit_backs_up_original(tmp_path):
    """track_edit 改前备份:备份文件存在于 backup_root,内容=改前原版。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"
    a.write_text("原版", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)
    # 初始 snapshot 持有 a 的 v1 backup
    snap0 = fh.snapshots[-1]
    assert str(a.resolve()) in snap0.tracked
    backup = snap0.tracked[str(a.resolve())]
    assert backup.backup_file_name is not None
    assert (fh.backup_root / backup.backup_file_name).read_text(encoding="utf-8") == "原版"


def test_track_edit_dedup_in_same_snapshot(tmp_path):
    """track_edit 同一 snapshot 内重复调同一文件 -> 只备份一次(防覆盖 v1)。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"
    a.write_text("v1", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)
    # 第二次调(同 snapshot):文件改成"v2"再 track,不应覆盖 v1 backup
    a.write_text("v2", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)
    backup = fh.snapshots[-1].tracked[str(a.resolve())]
    assert backup.version == 1
    # backup_root 里 a 的 backup 文件只有 1 个(v1 内容,没被 v2 覆盖)
    assert (fh.backup_root / backup.backup_file_name).read_text(encoding="utf-8") == "v1"


def test_track_edit_null_backup_for_new_file(tmp_path):
    """track_edit 新建文件(文件不存在)-> 记 null backup(backup_file_name=None)。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "new.txt"   # 不存在
    fh.track_edit(str(a), step_id=0)
    backup = fh.snapshots[-1].tracked[str(a.resolve())]
    assert backup.backup_file_name is None     # null backup
    assert backup.version == 1


def test_make_snapshot_mtime_optimization(tmp_path):
    """make_snapshot mtime 优化:未改文件复用上次 backup 引用(不新增 backup 文件)。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)           # v1
    a.write_text("y", encoding="utf-8")        # 改了
    fh.make_snapshot(step_id=0)                # snap(0):a 改了 -> v2(新 backup 文件)
    snap0 = fh.snapshots[-1]
    v2_name = snap0.tracked[str(a.resolve())].backup_file_name
    # step 1 不改 a,直接 make_snapshot -> 复用 v2 引用,不新建 backup 文件
    fh.make_snapshot(step_id=1)
    snap1 = fh.snapshots[-1]
    assert snap1.tracked[str(a.resolve())].backup_file_name == v2_name   # 复用,同一文件名
    # backup_root 里只有 v1、v2 两个 backup 文件(没建 v3)
    assert len(list(fh.backup_root.iterdir())) == 2


def test_make_snapshot_version_monotonic(tmp_path):
    """make_snapshot version 单调递增:同一文件多次改,version 1->2->3。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"
    a.write_text("v1", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)           # 初始 snap: a=v1
    a.write_text("v2", encoding="utf-8"); fh.make_snapshot(0)   # snap(0): a=v2
    fh.track_edit(str(a), step_id=1)           # 跳过(snap(0) 已有 a)
    a.write_text("v3", encoding="utf-8"); fh.make_snapshot(1)   # snap(1): a=v3
    versions = [s.tracked[str(a.resolve())].version for s in fh.snapshots]
    assert versions == [1, 2, 3]


def test_rewind_restores_content(tmp_path):
    """rewind 还原内容:改两轮后 rewind 到初始 snapshot,文件内容回原版。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"
    a.write_text("原版", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)           # 初始 snap: a=v1(原版)
    a.write_text("改1", encoding="utf-8"); fh.make_snapshot(0)
    fh.track_edit(str(a), step_id=1)           # 跳过
    a.write_text("改2", encoding="utf-8"); fh.make_snapshot(1)
    assert a.read_text(encoding="utf-8") == "改2"
    changed = fh.rewind(INITIAL_STEP_ID)       # 回原版
    assert a.read_text(encoding="utf-8") == "原版"
    assert str(a.resolve()) in changed


def test_rewind_deletes_new_file(tmp_path):
    """rewind 删除新建文件:Write 新文件后 rewind,null backup -> 文件被 unlink 删除。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "new.txt"                   # 不存在
    fh.track_edit(str(a), step_id=0)           # 初始 snap: a=null backup(v1)
    a.write_text("新建内容", encoding="utf-8")  # 模拟 Write 创建
    fh.make_snapshot(0)                        # snap(0): a=v2(新建后内容)
    assert a.exists()
    fh.rewind(INITIAL_STEP_ID)                 # null backup -> unlink
    assert not a.exists()


def test_rewind_returns_changed_files_only(tmp_path):
    """rewind 返回变更文件列表(只列实际改动的;未改的不列)。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"; a.write_text("a原", encoding="utf-8")
    b = tmp_path / "b.txt"; b.write_text("b原", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)
    fh.track_edit(str(b), step_id=0)
    a.write_text("a改", encoding="utf-8")      # 只改 a
    fh.make_snapshot(0)
    fh.rewind(INITIAL_STEP_ID)                 # 回原版
    # 再 rewind 到 snap(0)(a=v2 改后,b=v1 原版未改)
    a.write_text("a再改", encoding="utf-8")
    changed = fh.rewind(0)
    # a 从"a再改"还原到"a改"(snap0 的 v2),b 此时是原版==snap0 的 v1 -> 不变
    assert str(a.resolve()) in changed
    assert a.read_text(encoding="utf-8") == "a改"


def test_max_snapshots_evicts_oldest(tmp_path):
    """MAX_SNAPSHOTS=100:超 100 丢最老,seq 单调递增不回退。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"; a.write_text("x", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)
    for i in range(105):
        fh.make_snapshot(i)
    assert len(fh.snapshots) == MAX_SNAPSHOTS
    assert fh.seq == 105                       # 单调递增,不回退
    assert fh.can_restore(INITIAL_STEP_ID) is False   # 最老(初始 -1)被丢
    assert fh.can_restore(104) is True         # 最新的还在


def test_can_restore(tmp_path):
    """can_restore(step_id) 判断是否存在该 snapshot。"""
    fh = FileHistory(tmp_path / "fh")
    assert fh.can_restore(INITIAL_STEP_ID) is True
    assert fh.can_restore(0) is False
    fh.make_snapshot(0)
    assert fh.can_restore(0) is True
    assert fh.can_restore(999) is False


def test_rewind_to_intermediate_step(tmp_path):
    """rewind 到中间 step:改三轮后 rewind 到 step 0(第一轮改后),内容=第一轮改后。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"; a.write_text("原版", encoding="utf-8")
    fh.track_edit(str(a), step_id=0)
    a.write_text("改1", encoding="utf-8"); fh.make_snapshot(0)
    fh.track_edit(str(a), step_id=1)
    a.write_text("改2", encoding="utf-8"); fh.make_snapshot(1)
    fh.track_edit(str(a), step_id=2)
    a.write_text("改3", encoding="utf-8"); fh.make_snapshot(2)
    fh.rewind(0)                               # 回"step 0 改后"
    assert a.read_text(encoding="utf-8") == "改1"


# ============ Read 工具 ============

def test_read_returns_numbered_lines(tmp_path):
    """读文件返回带行号内容(cat -n 格式:{行号}\t{内容})。"""
    a = tmp_path / "a.txt"; a.write_text("第一行\n第二行\n第三行", encoding="utf-8")
    out = _tool("read").handler(file_path=str(a))
    assert "1\t第一行" in out
    assert "2\t第二行" in out
    assert "3\t第三行" in out


def test_read_records_state(tmp_path):
    """读后 read_file_state[abs_path] 记 content + mtime + is_partial=False。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    rec = _runtime_state.read_file_state[str(a.resolve())]
    assert rec.content == "hello"
    assert rec.is_partial is False
    assert rec.mtime == a.stat().st_mtime


def test_read_partial_is_partial(tmp_path):
    """部分读(offset/limit)-> is_partial=True。"""
    a = tmp_path / "a.txt"; a.write_text("l1\nl2\nl3\nl4", encoding="utf-8")
    _tool("read").handler(file_path=str(a), offset=1, limit=2)
    rec = _runtime_state.read_file_state[str(a.resolve())]
    assert rec.is_partial is True


def test_read_missing_file_errors(tmp_path):
    """读不存在的文件 -> 报错(清晰,不崩)。"""
    with pytest.raises(FileNotFoundError):
        _tool("read").handler(file_path=str(tmp_path / "no.txt"))


def test_read_empty_file_ok(tmp_path):
    """读空文件 -> 返回空(不报错)。"""
    a = tmp_path / "empty.txt"; a.write_text("", encoding="utf-8")
    out = _tool("read").handler(file_path=str(a))
    assert out == ""


# ============ Edit 工具 ============

def test_edit_requires_read_first(tmp_path):
    """先读后改:没 Read 直接 Edit -> 报错 Read it first。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match="Read it first"):
        _tool("edit").handler(file_path=str(a), old_string="hello", new_string="hi")


def test_edit_stale_detection(tmp_path):
    """陈旧检测:Read 后外部改文件(mtime 变+内容变)-> Edit 报 modified since read。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    a.write_text("外部改", encoding="utf-8")   # mtime 变 + 内容变
    with pytest.raises(ValueError, match="modified since read"):
        _tool("edit").handler(file_path=str(a), old_string="hello", new_string="hi")


def test_edit_stale_mtime_only_no_error(tmp_path):
    """陈旧兜底:Read 后 mtime 变但内容没变(Windows 云同步)-> 不报错,正常改。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    future = time.time() + 10
    os.utime(a, (future, future))              # 只动 mtime,内容不变
    r = _tool("edit").handler(file_path=str(a), old_string="hello", new_string="hi")
    assert "Edited" in r
    assert a.read_text(encoding="utf-8") == "hi"


def test_edit_string_not_found(tmp_path):
    """old_string 不存在 -> 报错 String not found。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    with pytest.raises(ValueError, match="String not found"):
        _tool("edit").handler(file_path=str(a), old_string="xyz", new_string="hi")


def test_edit_multiple_matches_no_replace_all(tmp_path):
    """old_string 多处匹配 + replace_all=False -> 报错 Found N matches。"""
    a = tmp_path / "a.txt"; a.write_text("foo bar foo", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    with pytest.raises(ValueError, match="Found 2 matches"):
        _tool("edit").handler(file_path=str(a), old_string="foo", new_string="baz")


def test_edit_replace_all(tmp_path):
    """replace_all=True -> 全量替换。"""
    a = tmp_path / "a.txt"; a.write_text("foo bar foo", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    _tool("edit").handler(file_path=str(a), old_string="foo", new_string="baz", replace_all=True)
    assert a.read_text(encoding="utf-8") == "baz bar baz"


def test_edit_rejects_empty_old_string(tmp_path):
    """#13: 空 old_string 守卫--否则 content.replace("",new) 在每字符间插入,静默损坏整文件
    (count("")=len+1;replace_all=True 时 'hello'.replace('','X')='XhXeXlXlXoX')。对标 CC 拒绝空 old_string。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))   # 先读,过"先读后改"闸门,证明守卫在其后仍拦住
    with pytest.raises(ValueError, match="empty"):
        _tool("edit").handler(file_path=str(a), old_string="", new_string="X", replace_all=True)
    assert a.read_text(encoding="utf-8") == "hello"   # 文件未被破坏


def test_edit_rejects_same_old_new(tmp_path):
    """#13: old==new 是无意义替换,守卫拒绝。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    with pytest.raises(ValueError, match="differ"):
        _tool("edit").handler(file_path=str(a), old_string="hello", new_string="hello")


def test_edit_single_replace_updates_state(tmp_path):
    """正常单次替换成功 + 更新 read_file_state(新内容 + 新 mtime)。"""
    a = tmp_path / "a.txt"; a.write_text("hello", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    _tool("edit").handler(file_path=str(a), old_string="hello", new_string="hi")
    rec = _runtime_state.read_file_state[str(a.resolve())]
    assert rec.content == "hi"
    assert rec.mtime == a.stat().st_mtime


def test_edit_backs_up_via_before_mutation(tmp_path):
    """改前 trackEdit 已备份:Edit 经 executor + before_mutation,backup_root 有原版;rewind 还原。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"; a.write_text("原版", encoding="utf-8")
    _tool("read").handler(file_path=str(a))
    executor = ToolExecutor(registry, before_mutation=lambda c: fh.track_edit(c.arguments["file_path"], 0))
    r = executor.execute(ToolCall(call_id="c1", tool_name="edit",
        arguments={"file_path": str(a), "old_string": "原版", "new_string": "改后"}))
    assert r.ok, r.error
    assert a.read_text(encoding="utf-8") == "改后"
    assert len(list(fh.backup_root.iterdir())) == 1   # v1 备份(原版)
    fh.rewind(INITIAL_STEP_ID)
    assert a.read_text(encoding="utf-8") == "原版"


# ============ Write 工具 ============

def test_write_creates_new_file_mkdir(tmp_path):
    """创建新文件成功(父目录不存在自动建)。"""
    a = tmp_path / "sub" / "dir" / "a.txt"
    _tool("write").handler(file_path=str(a), content="new")
    assert a.read_text(encoding="utf-8") == "new"


def test_write_overwrite_requires_read(tmp_path):
    """覆盖已有文件需先 Read(没 Read 报错 File exists. Read it first)。"""
    a = tmp_path / "a.txt"; a.write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="File exists. Read it first"):
        _tool("write").handler(file_path=str(a), content="new")


def test_write_empty_file_no_read_needed(tmp_path):
    """覆盖空文件不需先 Read(空文件视同新建)。"""
    a = tmp_path / "a.txt"; a.write_text("", encoding="utf-8")
    _tool("write").handler(file_path=str(a), content="new")
    assert a.read_text(encoding="utf-8") == "new"


def test_write_updates_state(tmp_path):
    """写后 read_file_state 更新。"""
    a = tmp_path / "a.txt"
    _tool("write").handler(file_path=str(a), content="new")
    rec = _runtime_state.read_file_state[str(a.resolve())]
    assert rec.content == "new"


def test_write_backs_up_existing_via_before_mutation(tmp_path):
    """Write 覆盖已有文件前 trackEdit 备份(经 before_mutation);rewind 还原。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "a.txt"; a.write_text("原版", encoding="utf-8")
    _tool("read").handler(file_path=str(a))   # 覆盖需先 Read
    executor = ToolExecutor(registry, before_mutation=lambda c: fh.track_edit(c.arguments["file_path"], 0))
    r = executor.execute(ToolCall(call_id="c1", tool_name="write",
        arguments={"file_path": str(a), "content": "全新内容"}))
    assert r.ok, r.error
    assert a.read_text(encoding="utf-8") == "全新内容"
    assert len(list(fh.backup_root.iterdir())) == 1
    fh.rewind(INITIAL_STEP_ID)
    assert a.read_text(encoding="utf-8") == "原版"


def test_write_new_file_rewind_deletes(tmp_path):
    """Write 新文件 -> rewind -> 文件被删(null backup 闭环)。"""
    fh = FileHistory(tmp_path / "fh")
    a = tmp_path / "new.txt"
    executor = ToolExecutor(registry, before_mutation=lambda c: fh.track_edit(c.arguments["file_path"], 0))
    r = executor.execute(ToolCall(call_id="c1", tool_name="write",
        arguments={"file_path": str(a), "content": "新建"}))
    assert r.ok, r.error
    assert a.exists()
    fh.make_snapshot(0)
    fh.rewind(INITIAL_STEP_ID)                 # null backup -> unlink
    assert not a.exists()


# ============ Bash 工具 ============

def test_bash_success(tmp_path):
    """执行命令返回 {stdout, stderr, exit_code};成功 exit_code=0。"""
    r = _tool("bash").handler(command="echo hello")
    assert r["exit_code"] == 0
    assert "hello" in r["stdout"]


def test_bash_failure_returns_exit_code(tmp_path):
    """失败命令 exit_code!=0(不抛异常,把 exit_code 返回)。"""
    r = _tool("bash").handler(command='python -c "import sys; sys.exit(7)"')
    assert r["exit_code"] == 7


def test_bash_timeout(tmp_path):
    """超时:timeout=1 + 长命令 -> 抛 ToolTimeoutError。"""
    from agent.core.errors import ToolTimeoutError
    with pytest.raises(ToolTimeoutError):
        _tool("bash").handler(command='python -c "import time; time.sleep(3)"', timeout=1)


def test_bash_captures_stderr(tmp_path):
    """stdout/stderr 正确捕获。"""
    r = _tool("bash").handler(command='python -c "import sys; print(\'err\', file=sys.stderr)"')
    assert "err" in r["stderr"]


# ============ Glob 工具 ============

def test_glob_finds_files(tmp_path):
    """glob **/*.py 返回匹配文件路径列表。"""
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    r = _tool("glob").handler(pattern="**/*.py", path=str(tmp_path))
    r_norm = [p.replace("\\", "/") for p in r]
    assert any(p.endswith("a.py") for p in r_norm)
    assert any(p.endswith("b.py") for p in r_norm)
    assert not any(p.endswith("c.txt") for p in r_norm)


def test_glob_sorted_by_mtime(tmp_path):
    """结果按 mtime 倒序(最近修改在前)。"""
    old = tmp_path / "old.py"; old.write_text("x")
    time.sleep(0.01)
    new = tmp_path / "new.py"; new.write_text("x")
    r = _tool("glob").handler(pattern="*.py", path=str(tmp_path))
    r_norm = [p.replace("\\", "/") for p in r]
    assert r_norm[0].endswith("new.py")   # 最近修改在前


def test_glob_no_match(tmp_path):
    """无匹配返回 [](不报错)。"""
    r = _tool("glob").handler(pattern="**/*.xyz", path=str(tmp_path))
    assert r == []


# ============ Grep 工具 ============

def test_grep_files_with_matches(tmp_path):
    """output_mode=files_with_matches -> 返回匹配文件路径列表。"""
    (tmp_path / "a.py").write_text("def foo():\n    pass", encoding="utf-8")
    (tmp_path / "b.py").write_text("def bar():\n    pass", encoding="utf-8")
    (tmp_path / "c.txt").write_text("foo", encoding="utf-8")
    r = _tool("grep").handler(pattern=r"def\s+\w+", path=str(tmp_path),
                              glob="*.py", output_mode="files_with_matches")
    r_norm = [p.replace("\\", "/") for p in r]
    assert any(p.endswith("a.py") for p in r_norm)
    assert any(p.endswith("b.py") for p in r_norm)
    assert not any(p.endswith("c.txt") for p in r_norm)   # glob 过滤


def test_grep_content_mode(tmp_path):
    """output_mode=content -> 返回匹配行(带行号)。"""
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    r = _tool("grep").handler(pattern=r"def\s+\w+", path=str(tmp_path), output_mode="content")
    joined = "\n".join(r)
    assert "def foo" in joined
    assert ":1:" in joined                      # 行号 1


def test_grep_count_mode(tmp_path):
    """output_mode=count -> 返回匹配数。"""
    (tmp_path / "a.py").write_text("foo\nfoo\nbar\n", encoding="utf-8")
    r = _tool("grep").handler(pattern="foo", path=str(tmp_path), output_mode="count")
    assert any(v == 2 for v in r.values())


def test_grep_no_match(tmp_path):
    """无匹配返回空。"""
    (tmp_path / "a.py").write_text("hello", encoding="utf-8")
    r = _tool("grep").handler(pattern="xyz", path=str(tmp_path), output_mode="files_with_matches")
    assert r == []


def test_grep_regex_pattern(tmp_path):
    """正则 pattern 正确解析(如 'function foo' 这种)。"""
    (tmp_path / "a.py").write_text("function foo\nfunction bar\n", encoding="utf-8")
    r = _tool("grep").handler(pattern=r"function\s+\w+", path=str(tmp_path),
                              output_mode="files_with_matches")
    assert len(r) == 1


# ============ 集成(闭环,经 agentloop + before_mutation + make_snapshot)============

class _ScriptedAdapter(BaseModelAdapter):
    """按脚本返回 ModelResponse(同 test_smoke 模式,继承 BaseModelAdapter 获默认 stream_llm)。"""
    def __init__(self, script):
        super().__init__(api_key="", base_url="", model="")
        self.script = list(script)

    async def call_llm(self, request):
        if self.script:
            return self.script.pop(0)
        return ModelResponse(text="done")

    def append_assistant(self, messages, r):
        return messages + [Message(role="assistant", content=r.text or "")]

    def append_tool_result(self, messages, result):
        return messages + [Message(role="tool", content=result.text or "")]


def test_integration_read_edit_rewind(tmp_path):
    """集成闭环:Read -> Edit -> rewind 回原版(经 agentloop + before_mutation + make_snapshot)。"""
    a = tmp_path / "a.txt"; a.write_text("原版", encoding="utf-8")
    fh = FileHistory(tmp_path / "fh")
    _runtime_state.file_history.set(fh)
    adapter = _ScriptedAdapter([
        ModelResponse(text=None, tool_calls=[ToolCall(call_id="c1", tool_name="read",
            arguments={"file_path": str(a)})]),
        ModelResponse(text=None, tool_calls=[ToolCall(call_id="c2", tool_name="edit",
            arguments={"file_path": str(a), "old_string": "原版", "new_string": "改后"})]),
        ModelResponse(text="done"),
    ])
    executor = ToolExecutor(registry, before_mutation=_track_edit_callback)
    ctx = RuntimeContext(registry=registry, model_adapter=adapter, tool_executor=executor,
                         config=AgentConfig(max_steps=5), state=AgentState())
    asyncio.run(agentloop("改一下", ctx))
    assert a.read_text(encoding="utf-8") == "改后"
    fh.rewind(INITIAL_STEP_ID)   # make_snapshot 已在每步末调,rewind 回原版
    assert a.read_text(encoding="utf-8") == "原版"


def test_integration_write_new_file_rewind_deletes(tmp_path):
    """集成闭环:Write 新文件 -> rewind -> 文件被删(null backup,经 agentloop)。"""
    a = tmp_path / "new.txt"
    fh = FileHistory(tmp_path / "fh")
    _runtime_state.file_history.set(fh)
    adapter = _ScriptedAdapter([
        ModelResponse(text=None, tool_calls=[ToolCall(call_id="c1", tool_name="write",
            arguments={"file_path": str(a), "content": "新建内容"})]),
        ModelResponse(text="done"),
    ])
    executor = ToolExecutor(registry, before_mutation=_track_edit_callback)
    ctx = RuntimeContext(registry=registry, model_adapter=adapter, tool_executor=executor,
                         config=AgentConfig(max_steps=5), state=AgentState())
    asyncio.run(agentloop("建文件", ctx))
    assert a.exists()
    assert a.read_text(encoding="utf-8") == "新建内容"
    fh.rewind(INITIAL_STEP_ID)   # null backup -> unlink
    assert not a.exists()


def test_integration_read_edit_bash_rewind(tmp_path):
    """完整闭环:Read -> Edit -> Bash 验证 -> rewind 回原版(对标 CC 自主改码 + 回滚)。"""
    a = tmp_path / "a.txt"; a.write_text("version=1", encoding="utf-8")
    fh = FileHistory(tmp_path / "fh")
    _runtime_state.file_history.set(fh)
    adapter = _ScriptedAdapter([
        ModelResponse(text=None, tool_calls=[ToolCall(call_id="c1", tool_name="read",
            arguments={"file_path": str(a)})]),
        ModelResponse(text=None, tool_calls=[ToolCall(call_id="c2", tool_name="edit",
            arguments={"file_path": str(a), "old_string": "version=1", "new_string": "version=2"})]),
        ModelResponse(text=None, tool_calls=[ToolCall(call_id="c3", tool_name="bash",
            arguments={"command": "echo ok", "timeout": 5})]),
        ModelResponse(text="done"),
    ])
    executor = ToolExecutor(registry, before_mutation=_track_edit_callback)
    ctx = RuntimeContext(registry=registry, model_adapter=adapter, tool_executor=executor,
                         config=AgentConfig(max_steps=6), state=AgentState())
    asyncio.run(agentloop("改并验证", ctx))
    assert a.read_text(encoding="utf-8") == "version=2"
    fh.rewind(INITIAL_STEP_ID)
    assert a.read_text(encoding="utf-8") == "version=1"


# ============ WebSearch 工具(步3,接 Tavily)============

def test_web_search_empty_query():
    """query 为空 -> 报错。"""
    with pytest.raises(ValueError):
        _tool("web_search").handler(query="")


def test_web_search_both_domains():
    """allowed_domains + blocked_domains 同时传 -> 报错(对标 CC validateInput)。"""
    with pytest.raises(ValueError):
        _tool("web_search").handler(query="x", allowed_domains=["a.com"], blocked_domains=["b.com"])


def test_web_search_formats_results(monkeypatch):
    """mock Tavily 返回 -> 格式化正确 + 含 Sources。"""
    import httpx

    class _FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [{"title": "T1", "url": "http://a.com", "content": "CCC"}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp())
    monkeypatch.setenv("TAVILY_API_KEY", "fake")
    r = _tool("web_search").handler(query="test")
    assert "T1" in r
    assert "http://a.com" in r
    assert "Sources" in r   # 对标 CC 强制 sources


def test_web_search_network_error(monkeypatch):
    """mock 网络错误 -> raise ConnectionError(可重试,进可靠性管道),不再 return dict 被标 ok=True。"""
    import httpx

    def boom(*a, **k):
        raise httpx.HTTPError("boom")
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setenv("TAVILY_API_KEY", "fake")
    with pytest.raises(ConnectionError):
        _tool("web_search").handler(query="test")


# ============ WebFetch 工具(步3,httpx + LLM 提取)============

class _MockAdapter:
    """WebFetch 测试用:call_llm 返回固定提取结果(不调真实 LLM)。"""
    async def call_llm(self, request):
        class R:
            text = "提取结果:Hello"
        return R()


def test_web_fetch_http_to_https(monkeypatch):
    """HTTP URL -> 自动升 HTTPS。"""
    import httpx

    captured = {}

    class _FakeResp:
        is_redirect = False
        status_code = 200
        text = "<p>hi</p>"

    def fake_get(url, timeout=None, follow_redirects=None):
        captured["url"] = url
        return _FakeResp()
    monkeypatch.setattr(httpx, "get", fake_get)
    _runtime_state.model_adapter.set(_MockAdapter())
    _tool("web_fetch").handler(url="http://example.com", prompt="总结")
    assert captured["url"].startswith("https://")


def test_web_fetch_redirect(monkeypatch):
    """跨域重定向 -> 返回 REDIRECT 提示,不跟随。"""
    import httpx

    class _FakeResp:
        is_redirect = True
        status_code = 302
        headers = {"location": "https://other.com"}
        text = ""
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())
    r = _tool("web_fetch").handler(url="https://x.com", prompt="总结")
    assert "REDIRECT" in r and "other.com" in r


def test_web_fetch_extracts(monkeypatch):
    """mock httpx 返回 HTML + mock model_adapter -> 返回提取结果。"""
    import httpx

    class _FakeResp:
        is_redirect = False
        status_code = 200
        text = "<html><body><p>Hello world</p></body></html>"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())
    _runtime_state.model_adapter.set(_MockAdapter())
    r = _tool("web_fetch").handler(url="https://x.com", prompt="总结")
    assert "Hello" in r


def test_web_fetch_invalid_url():
    """无效 URL -> raise ValueError(不重试),不再 return dict 被标 ok=True。"""
    with pytest.raises(ValueError):
        _tool("web_fetch").handler(url="ftp://x.com", prompt="x")


def test_web_fetch_network_error(monkeypatch):
    """mock 网络错误 -> raise ConnectionError(可重试,进可靠性管道),不再 return dict 被标 ok=True。"""
    import httpx

    def boom(*a, **k):
        raise httpx.HTTPError("boom")
    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(ConnectionError):
        _tool("web_fetch").handler(url="https://x.com", prompt="x")


# ============ TodoWrite 工具(步4,无状态 + nudge)============

def test_todo_write_normal():
    """正常更新 todos -> 返回确认。"""
    r = _tool("todo_write").handler(todos=[
        {"content": "A", "status": "in_progress", "activeForm": "Doing A"}])
    assert "Todos updated" in r


def test_todo_write_nudge_on_3_done_no_verify():
    """关 3+ 项且无 verify -> 返回含验证提示。"""
    r = _tool("todo_write").handler(todos=[
        {"content": "A", "status": "completed", "activeForm": "A"},
        {"content": "B", "status": "completed", "activeForm": "B"},
        {"content": "C", "status": "completed", "activeForm": "C"},
    ])
    assert "验证" in r   # nudge 触发


def test_todo_write_no_nudge_with_verify():
    """关 3+ 项但有 verify 步骤 -> 不含提示。"""
    r = _tool("todo_write").handler(todos=[
        {"content": "A", "status": "completed", "activeForm": "A"},
        {"content": "B", "status": "completed", "activeForm": "B"},
        {"content": "verify tests pass", "status": "completed", "activeForm": "Verifying"},
    ])
    assert "先验证" not in r   # has_verify -> 不 nudge


def test_todo_write_no_nudge_fewer_than_3():
    """关 < 3 项 -> 不含提示。"""
    r = _tool("todo_write").handler(todos=[
        {"content": "A", "status": "completed", "activeForm": "A"},
        {"content": "B", "status": "completed", "activeForm": "B"},
    ])
    assert "先验证" not in r


# ============ AskUserQuestion 工具(步4,REPL input)============

def test_ask_user_single_select(monkeypatch):
    """mock input 返回 '2' -> answer = [opt2]。"""
    monkeypatch.setattr("builtins.input", lambda *a: "2")
    r = _tool("ask_user").handler(questions=[{
        "question": "选哪个", "header": "选", "options": [{"label": "A"}, {"label": "B"}]
    }])
    assert r[0]["answer"] == ["B"]


def test_ask_user_multi_select(monkeypatch):
    """mock input 返回 '1,3' -> answer = [opt1, opt3]。"""
    monkeypatch.setattr("builtins.input", lambda *a: "1,3")
    r = _tool("ask_user").handler(questions=[{
        "question": "选哪些", "header": "多选", "multiSelect": True,
        "options": [{"label": "A"}, {"label": "B"}, {"label": "C"}]
    }])
    assert r[0]["answer"] == ["A", "C"]


def test_ask_user_default_first(monkeypatch):
    """mock input 返回空 -> 默认第一项。"""
    monkeypatch.setattr("builtins.input", lambda *a: "")
    r = _tool("ask_user").handler(questions=[{
        "question": "选", "header": "h", "options": [{"label": "A"}, {"label": "B"}]
    }])
    assert r[0]["answer"] == ["A"]


def test_ask_user_schema_rejects_one_option():
    """options < 2 -> schema 校验拒绝(走 executor _precheck)。"""
    executor = ToolExecutor(registry)
    r = executor.execute(ToolCall(call_id="c1", tool_name="ask_user",
        arguments={"questions": [{"question": "q", "header": "h", "options": [{"label": "only"}]}]}))
    assert not r.ok
    assert (r.error or {}).get("type") == "SchemaValidationError"


# ============ P2 回归 ============

def test_track_edit_uses_workspace_path(tmp_path):
    """#2: _track_edit_callback 用 ws.resolve 解析路径(与 edit/write 一致),否则 workspace≠cwd 时
    backup key(cwd-based)与实际改的文件(workspace-based)不一致,rewind 回滚到错文件。"""
    from agent.agentloop import _track_edit_callback
    from agent.core.workspace import Workspace
    ws_root = tmp_path / "ws"; ws_root.mkdir()
    fh = FileHistory(tmp_path / "fh")
    _runtime_state.file_history.set(fh)
    _runtime_state.workspace.set(Workspace(root=ws_root))
    _runtime_state.current_step_id.set(0)
    # 相对路径 "a.txt" -> ws.resolve -> ws_root/a.txt(不是 cwd/a.txt)
    _track_edit_callback(ToolCall(call_id="c1", tool_name="edit",
                                  arguments={"file_path": "a.txt"}))
    key = str((ws_root / "a.txt").resolve())
    assert key in fh.snapshots[-1].tracked   # backup key 是 workspace 路径,非 cwd


def test_idempotency_get_returns_copy():
    """#7: IdempotencyStore.get 返回 deepcopy,调用方改 data 不污染缓存(修复前返回浅引用)。"""
    from agent.reliability.idempotency import IdempotencyStore
    store = IdempotencyStore()
    call = ToolCall(call_id="c1", tool_name="t", arguments={})
    store.set(call, {"v": [1, 2, 3]})
    got = store.get(call)
    got["v"].append(999)                          # 改返回值
    assert store.get(call)["v"] == [1, 2, 3]      # 缓存未被污染
