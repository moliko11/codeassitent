"""P0 git 白名单门禁验收测试(guardrails/git_safety.py)。

覆盖 docs/cc-git-integration.md「实现优先级」P0:
- 只读白名单(log/diff/show/blame/status)免确认放行
- 其余 git 子命令(写命令)-> ask
- config 注入 flag(-c/--exec-path/--config-env)-> 硬拦 block
- 归一化:剥 env var 前缀 + shell quote 后再判(防绕过)
- 复合命令 / 命令替换含 git -> ask(防 git log && rm 绕过)

不依赖真实 LLM / 真实 git:分类器纯函数单测;guardrail 用 mock confirmer;
executor 级只测 block / ask-denied 两条(均在 subprocess 前短路,不跑 git)。
运行(从 code/ 目录,3.12 venv):python -m pytest tests/test_git_safety.py -v
"""
import pytest

from agent.guardrails import GitSafetyGuard, GuardrailRunner, classify_git_command, GitDecision
from agent.guardrails.guardrail import GuardrailResult
from agent.tools.defs import ToolCall, ToolSpec, Tool
from agent.tools.registry import ToolRegistry, ToolExecutor


# ─────────────────── 分类器(纯函数)───────────────────

def test_readonly_subcommands_allowed():
    """5 个只读子命令免确认(allow),带常见 flag 也放行(P0 不做 per-flag 校验)。"""
    for cmd in ["git log", "git diff", "git show", "git blame", "git status"]:
        assert classify_git_command(cmd) == GitDecision.ALLOW, cmd
    # 常见只读 flag(P0 全放 flag,只硬拦 -c 那三个)
    assert classify_git_command("git log --oneline -5") == GitDecision.ALLOW
    assert classify_git_command("git diff --cached --stat") == GitDecision.ALLOW
    assert classify_git_command("git show HEAD") == GitDecision.ALLOW
    assert classify_git_command("git status --porcelain") == GitDecision.ALLOW


def test_write_subcommands_ask():
    """不在白名单的 git 子命令(写命令)-> ask(需用户确认)。"""
    for cmd in [
        "git push", "git commit -m x", "git reset --hard", "git merge dev",
        "git rebase main", "git add .", "git checkout -b feat", "git clean -fd",
        "git fetch", "git pull", "git clone https://example.com/r.git",
        "git stash drop", "git branch -D feat", "git tag v1",
    ]:
        assert classify_git_command(cmd) == GitDecision.ASK, cmd


def test_config_injection_flags_blocked():
    """-c / --exec-path / --config-env 任意位置出现即硬拦(能 RCE),即便子命令只读。"""
    assert classify_git_command("git -c core.fsmonitor=evil status") == GitDecision.BLOCK
    assert classify_git_command("git -c diff.external=hack log") == GitDecision.BLOCK
    assert classify_git_command("git --exec-path=/tmp/evil log") == GitDecision.BLOCK
    assert classify_git_command("git --exec-path=/x status") == GitDecision.BLOCK
    assert classify_git_command("git --config-env=core.fsmonitor=EVIL status") == GitDecision.BLOCK
    # 连写 --flag=value 形式
    assert classify_git_command("git --exec-path=/x show") == GitDecision.BLOCK


def test_non_git_commands_pass_through():
    """非 git 命令 -> not_git(放行,交后续 guardrail / 执行)。"""
    assert classify_git_command("echo hello") == GitDecision.NOT_GIT
    assert classify_git_command("ls -la") == GitDecision.NOT_GIT
    assert classify_git_command("python -m pytest tests/") == GitDecision.NOT_GIT
    assert classify_git_command("") == GitDecision.NOT_GIT
    assert classify_git_command("rg pattern src/") == GitDecision.NOT_GIT


def test_env_var_prefix_normalized():
    """剥前导 env var 赋值前缀后再判:NO_COLOR=1 git status -> allow。"""
    assert classify_git_command("NO_COLOR=1 git status") == GitDecision.ALLOW
    assert classify_git_command("GIT_DIR=.git git log") == GitDecision.ALLOW
    # 多个 env 前缀
    assert classify_git_command("NO_COLOR=1 PAGER=cat git diff") == GitDecision.ALLOW
    # env 前缀 + 写命令 -> 仍 ask(归一化只影响识别,不改子命令)
    assert classify_git_command("NO_COLOR=1 git push") == GitDecision.ASK
    # env 前缀 + config 注入 -> 仍 block
    assert classify_git_command("NO_COLOR=1 git -c x=y status") == GitDecision.BLOCK


def test_shell_quote_normalized():
    """剥 shell quote 后再判:'git' status / "git" log -> allow。"""
    assert classify_git_command("'git' status") == GitDecision.ALLOW
    assert classify_git_command('"git" log') == GitDecision.ALLOW
    assert classify_git_command("'git' -c x=y status") == GitDecision.BLOCK  # quote 不影响 flag 拦截


def test_full_path_git_recognized():
    r"""完整路径 git 调用也识别(/usr/bin/git、git.exe)。

    注:Windows 反斜杠全路径(C:\tools\git.exe)是 cmd.exe 形式,非 bash 命令;
    本项目 BashTool 走 bash,agent 不会发该形式,且 shlex posix 会吃掉反斜杠,
    故不测。bash 全路径用正斜杠(/usr/bin/git)。
    """
    assert classify_git_command("/usr/bin/git log") == GitDecision.ALLOW
    assert classify_git_command("/usr/bin/git push") == GitDecision.ASK
    assert classify_git_command("git.exe status") == GitDecision.ALLOW


def test_compound_commands_ask():
    """复合命令 / 命令替换含 git -> ask(无法证明整体只读,防 git log && rm 绕过)。"""
    # 只读 git + 破坏性命令:不能因开头是 git log 就放行
    assert classify_git_command("git log && rm -rf /") == GitDecision.ASK
    assert classify_git_command("echo x && git push") == GitDecision.ASK  # 非 git 开头也拦
    assert classify_git_command("git status; rm -f x") == GitDecision.ASK
    assert classify_git_command("git log | head") == GitDecision.ASK      # 管道
    assert classify_git_command("git log $(evil)") == GitDecision.ASK     # 命令替换
    assert classify_git_command("git log `evil`") == GitDecision.ASK      # 反引号替换
    assert classify_git_command("git log --author=$USER") == GitDecision.ASK  # 变量展开
    assert classify_git_command("git log & bgcmd") == GitDecision.ASK     # 后台 &
    # 复合 + config 注入:BLOCK 优先于 ASK
    assert classify_git_command("git -c x=y log && rm -rf /") == GitDecision.BLOCK


def test_bare_git_ask():
    """裸 git(无子命令)-> ask(fail-safe,不属只读白名单)。"""
    assert classify_git_command("git") == GitDecision.ASK


def test_global_option_before_subcommand_ask():
    """git -C /path log:全局选项让 tokens[1] 非白名单 -> ask(fail-safe,P0 不跳全局选项)。"""
    assert classify_git_command("git -C /path log") == GitDecision.ASK
    assert classify_git_command("git --git-dir=.git status") == GitDecision.ASK


# ─────────────────── Guardrail(注入 mock confirmer)───────────────────

def _call(command):
    return ToolCall(call_id="c1", tool_name="bash", arguments={"command": command})


def _ctx():
    class _Ctx:
        config = None
        registry = None
    return _Ctx()


def test_guard_allow_readonly_no_confirm():
    """只读 git:不调 confirmer 即放行(用会抛异常的 confirmer 验证不被调)。"""
    def boom(command):
        raise AssertionError("只读命令不应调 confirmer")
    g = GitSafetyGuard(confirmer=boom)
    assert g.check(_call("git log"), _ctx()).action == "allow"
    assert g.check(_call("git diff HEAD"), _ctx()).action == "allow"


def test_guard_block_config_injection():
    """config 注入 flag:block(硬拦,不询问)。"""
    g = GitSafetyGuard()
    r = g.check(_call("git -c core.fsmonitor=evil status"), _ctx())
    assert r.action == "block"
    assert "RCE" in r.reason or "config 注入" in r.reason


def test_guard_ask_approved():
    """写命令 + confirmer=True -> allow。"""
    g = GitSafetyGuard(confirmer=lambda c: True)
    assert g.check(_call("git push"), _ctx()).action == "allow"
    assert g.check(_call("git commit -m x"), _ctx()).action == "allow"


def test_guard_ask_denied():
    """写命令 + confirmer=False -> block(回填模型:用户拒绝)。"""
    g = GitSafetyGuard(confirmer=lambda c: False)
    r = g.check(_call("git push"), _ctx())
    assert r.action == "block"
    assert "拒绝" in r.reason


def test_guard_non_bash_tool_passes():
    """非 bash 工具:放行(不归 git 门禁管)。"""
    g = GitSafetyGuard()
    other = ToolCall(call_id="c2", tool_name="read", arguments={"file_path": "x"})
    assert g.check(other, _ctx()).action == "allow"


def test_guard_non_git_bash_passes():
    """bash 但非 git 命令:放行(交执行)。"""
    g = GitSafetyGuard()
    assert g.check(_call("echo hello"), _ctx()).action == "allow"
    assert g.check(_call("ls -la"), _ctx()).action == "allow"


def test_guard_compound_ask_then_block_if_denied():
    """复合命令 git log && rm:ask;denied -> block(不静默执行 rm)。"""
    g = GitSafetyGuard(confirmer=lambda c: False)
    r = g.check(_call("git log && rm -rf /"), _ctx())
    assert r.action == "block"


# ─────────────────── executor 级接线(不跑 subprocess)───────────────────

def _registry_with_bash():
    import agent.tools  # 触发 bash 注册到默认 registry
    return agent.tools.registry


def test_executor_blocks_config_injection():
    """executor + GitSafetyGuard:git -c ... -> ToolResult ok=False, GuardrailBlocked(不跑 git)。"""
    reg = _registry_with_bash()
    runner = GuardrailRunner().register(GitSafetyGuard())
    exe = ToolExecutor(reg, guardrail_runner=runner, config=None)
    r = exe.execute(ToolCall(call_id="c1", tool_name="bash",
        arguments={"command": "git -c core.fsmonitor=evil status"}))
    assert r.ok is False
    assert r.error["type"] == "GuardrailBlocked"


def test_executor_ask_denied_returns_error():
    """executor + GitSafetyGuard(denied):git push -> ToolResult ok=False(回填模型)。"""
    reg = _registry_with_bash()
    runner = GuardrailRunner().register(GitSafetyGuard(confirmer=lambda c: False))
    exe = ToolExecutor(reg, guardrail_runner=runner, config=None)
    r = exe.execute(ToolCall(call_id="c2", tool_name="bash",
        arguments={"command": "git push"}))
    assert r.ok is False
    assert r.error["type"] == "GuardrailBlocked"
    assert "拒绝" in r.error["message"]


def test_executor_non_git_bash_runs():
    """executor + GitSafetyGuard:非 git bash 命令正常执行(门禁不拦)。"""
    reg = _registry_with_bash()
    runner = GuardrailRunner().register(GitSafetyGuard())
    exe = ToolExecutor(reg, guardrail_runner=runner, config=None)
    r = exe.execute(ToolCall(call_id="c3", tool_name="bash",
        arguments={"command": "echo ok"}))
    assert r.ok is True
    assert "ok" in r.data["stdout"]
