# guardrails/git_safety.py - BashTool 内 git 命令的白名单门禁(P0,对标 CC 工具内安全层)
#
# CC 的做法是白名单(allowlist)不是黑名单:只读子命令 + flag 校验通过 = 免确认放行;
# 不在白名单的(所有写命令)= 非只读 = fall through 到 ask;只有能 RCE 的才硬拦。
# 见 docs/cc-git-integration.md「工具内安全层」「实现优先级」两节。
#
# 本文件只做 P0+P1 最小可用(细节可简化,对标项目 impl-style):
# 1. 只读白名单:git log/diff/show/blame/status 免确认。其余 git 子命令 -> ask。
# 2. 硬拦 RCE / 任意写 flag:-c / --exec-path / --config-env(config 注入,能设 core.fsmonitor
#    等执行任意命令);--output=FILE(diff/log/show 任意文件写)。对标 readOnlyValidation.ts:1721-1745。
# 3. safeFlags 本期不做 per-flag 校验(留后续),只认子命令名 + 硬拦上述 flag。
# 4. 归一化后判定:剥 env var 前缀(NO_COLOR=1 git ...)和 shell quote('git' status)
#    再判,防绕过。对标 isNormalizedGitCommand(bashPermissions.ts:2567)。
# 5. 复合命令 / 命令替换( ; & | ` $( 换行 )含 git -> ask(无法证明整体只读)。
#    full per-subcommand 分析(自动放行 git log | head)留后续。cd+git 也由此覆盖(cd X && git)。
# 6. bare repo 检测:cwd 顶层含 HEAD/objects/refs(无 .git/HEAD)时,任何 git 命令 -> block
#    (跑 git 触发 cwd hooks = RCE)。对标 isCurrentDirectoryBareGitRepo(git.ts:876-925)。
#
# ask 入口:同步 confirmer(可注入)。默认 input() + 非 tty fail-closed 拒绝
# (对标 AskUserQuestionTool 的 stdin 简化路径;一次性 agentloop/CI 不跑写 git 命令)。
# 不走 needs_approval + waiting_approval:该路径续跑留 TODO(见 agentloop.py:149),
# 会卡住 REPL;P1 接好续跑后再升级。
import os
import re
import shlex
import sys
from typing import Callable, Optional

from .guardrail import Guardrail, GuardrailResult

# ---- 数据结构 ----

# 只读子命令白名单:免确认放行。其余 git 子命令(push/commit/reset/merge/rebase/add/
# checkout/clean/fetch/pull/clone/...)一律 ask。
GIT_READ_ONLY_SUBCOMMANDS = frozenset({"log", "diff", "show", "blame", "status"})

# config 注入 flag:任意位置出现即硬拦(能 RCE)。--exec-path / --config-env 支持
# --flag=value 连写形式,故用 startswith;-c 只支持空格分隔(-c key=val),用精确匹配。
# (对标 readOnlyValidation.ts:1721-1745)
GIT_CONFIG_INJECTION_FLAG_PREFIXES = ("--exec-path", "--config-env")

# 复合命令 / 命令替换指示符:含任一即视为非单条只读命令 -> ask。
# & 覆盖 &&,| 覆盖 ||,$ 覆盖 $VAR / $(...) / ${...},` 是命令替换,换行是命令分隔。
_RCE_OR_COMPOUND_CHARS = (";", "&", "|", "`", "$", "\n", "\r")

# 前导 env var 赋值前缀(NO_COLOR=1 git ... / GIT_DIR=.git git ...):VAR=value
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class GitDecision:
    """git 命令分类结果(字符串常量,便于测试断言)。"""
    NOT_GIT = "not_git"   # 非 git 命令:放行(交后续 guardrail / 执行)
    ALLOW = "allow"       # 只读 git:免确认放行
    ASK = "ask"           # 写 git / 复合命令:需用户确认
    BLOCK = "block"       # config 注入 flag:硬拦


# ---- 归一化 + 判定(纯函数,无副作用,单测友好)----

def _is_git_token(t: str) -> bool:
    r"""token 是否是 git 可执行名(含完整路径变体 /usr/bin/git、git.exe)。"""
    if t in ("git", "git.exe"):
        return True
    # 完整路径变体:要求路径分隔符前缀,避免误匹配 legit.exe 之类
    return t.endswith(("/git", "\\git", "/git.exe", "\\git.exe"))


def _normalize_tokens(command: str) -> list[str]:
    """剥 shell quote + 前导 env var 赋值前缀,返回 token 列表。

    对标 isNormalizedGitCommand(bashPermissions.ts:2567):'git' status -> git status,
    NO_COLOR=1 git status -> git status。shlex 处理 quote;解析失败降级 split(不致抛)。
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # quote 不闭合等:降级空白切分(丢失 quote 信息,但分类仍可 fail-safe)
        tokens = command.split()
    # 剥前导 env 赋值(可多个),遇到第一个非赋值 token(命令名)即停
    while tokens and _ENV_ASSIGNMENT_RE.match(tokens[0]):
        tokens.pop(0)
    return tokens


def _has_compound_or_rce(command: str) -> bool:
    """raw 命令是否含复合分隔符 / 命令替换(在归一化前的原串上判,防 git log&&rm 漏检)。"""
    return any(ch in command for ch in _RCE_OR_COMPOUND_CHARS)


def _is_bare_repo(cwd: str) -> bool:
    """cwd 是否被 git 当 bare repo(有 HEAD/objects/refs 但无有效 .git/HEAD)。

    bare repo 下跑 git 会触发 cwd 的 hooks/*(RCE)。对标 CC isCurrentDirectoryBareGitRepo
    (git.ts:876-925,三大沙箱逃逸之一)。普通仓库的 git 元数据在 .git/ 子目录,cwd 顶层无
    HEAD/objects/refs;bare repo 直接把这三者放在 cwd 顶层。worktree/submodule 的 .git 是文件,
    顶层也无此布局 -> 不误判。
    """
    head = os.path.join(cwd, "HEAD")
    objects = os.path.join(cwd, "objects")
    refs = os.path.join(cwd, "refs")
    if not (os.path.isfile(head) and os.path.isdir(objects) and os.path.isdir(refs)):
        return False
    # 有有效 .git/HEAD 则是普通仓库(防 cwd 既被当 bare 又有 .git 的诡异情形误判)
    if os.path.isfile(os.path.join(cwd, ".git", "HEAD")):
        return False
    return True


def classify_git_command(command: str) -> str:
    """分类一条 shell 命令中的 git 调用,返回 GitDecision.*。

    判定顺序:非 git -> NOT_GIT;含 config 注入 flag -> BLOCK;复合/替换 -> ASK;
    子命令在只读白名单 -> ALLOW;其余 -> ASK(fail-safe,白名单哲学:非只读即 ask)。
    """
    tokens = _normalize_tokens(command)
    if not any(_is_git_token(t) for t in tokens):
        return GitDecision.NOT_GIT

    # 硬拦能 RCE / 任意写的 flag(全局,任意位置出现都拒):
    # - config 注入(-c/--exec-path/--config-env):能设 core.fsmonitor 等执行任意命令(RCE)
    # - --output=FILE:diff/log/show 把输出写到任意路径(任意文件写/覆盖)
    for t in tokens:
        if t == "-c" or t.startswith(GIT_CONFIG_INJECTION_FLAG_PREFIXES):
            return GitDecision.BLOCK
        if t == "--output" or t.startswith("--output="):
            return GitDecision.BLOCK

    # 复合命令 / 命令替换含 git:无法证明整体只读 -> ask
    if _has_compound_or_rce(command):
        return GitDecision.ASK

    # 单条 git:子命令 = 第一个 git token 之后的首个 token(无则空串 -> ask)
    git_idx = next(i for i, t in enumerate(tokens) if _is_git_token(t))
    sub = tokens[git_idx + 1] if git_idx + 1 < len(tokens) else ""
    if sub in GIT_READ_ONLY_SUBCOMMANDS:
        return GitDecision.ALLOW
    return GitDecision.ASK


# ---- ask 入口(同步确认,可注入)----

def _default_confirmer(command: str) -> bool:
    """默认确认:REPL 用 input();非 tty(一次性 agentloop / CI)fail-closed 拒绝。

    fail-closed 对标 CC 非交互不跑写 git 命令:无法询问就拒绝,绝不静默执行。
    """
    if not sys.stdin.isatty():
        return False
    try:
        ans = input(f"\n[git 写命令需确认] {command}\n允许执行? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


# ---- Guardrail(before_tool)----

class GitSafetyGuard(Guardrail):
    """before_tool:BashTool 内 git 命令的白名单门禁。

    只对 tool_name=="bash" 生效;非 git 的 bash 命令放行(交后续 guardrail / 执行)。
    - ALLOW / NOT_GIT -> allow
    - BLOCK(config 注入 flag)-> block(硬拦,不询问)
    - ASK(写命令 / 复合)-> 同步 confirmer;通过 allow,否则 block
    """
    mount = "before_tool"
    name = "git_safety"

    def __init__(self, confirmer: Optional[Callable[[str], bool]] = None):
        # None -> 用模块默认 stdin 确认;测试 / 非 REPL 可注入 mock 或 fail-closed 闭包。
        self._confirmer = confirmer

    def check(self, payload, context) -> GuardrailResult:
        call = payload
        if call.tool_name != "bash":
            return GuardrailResult(passed=True, action="allow")
        command = (call.arguments or {}).get("command") or ""
        decision = classify_git_command(command)

        if decision == GitDecision.NOT_GIT:
            return GuardrailResult(passed=True, action="allow")

        # 是 git 命令:先查 bare repo(RCE via hooks),早于子命令判定,对标 CC
        # hasGitCommand && isCurrentDirectoryBareGitRepo()。getcwd 异常时 fail-open。
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = None
        if cwd is not None and _is_bare_repo(cwd):
            return GuardrailResult(
                passed=False, action="block",
                reason="当前目录是 bare git repo(顶层含 HEAD/objects/refs,无 .git/HEAD),"
                       "跑 git 会触发其 hooks(RCE),已硬拦",
            )

        if decision == GitDecision.ALLOW:
            return GuardrailResult(passed=True, action="allow")
        if decision == GitDecision.BLOCK:
            return GuardrailResult(
                passed=False, action="block",
                reason="git 命令含 config 注入 flag(-c/--exec-path/--config-env)或 --output,"
                       "已硬拦(防 RCE / 任意文件写)",
            )
        # ASK:同步确认
        confirmer = self._confirmer or _default_confirmer
        if confirmer(command):
            return GuardrailResult(passed=True, action="allow")
        return GuardrailResult(
            passed=False, action="block",
            reason=f"git 写命令未获用户确认,已拒绝:{command}",
        )
