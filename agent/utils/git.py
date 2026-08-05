"""git 仓库状态查询(spawn git 子进程 + 进程内缓存)。

对标 CC utils/git.ts 的状态查询,但简化:不抄零-spawn 文件读(CC 在沙箱里可能没 git,
且省进程开销;本项目无沙箱,直接 spawn 最简单可靠)。进程内 dict 缓存,会话级 prompt
首轮 build 一次 + 防重复 spawn。

全部 fail-open:非仓库 / git 未装 / 任何错误 -> 返回 None/False,不抛、不阻塞 prompt 组装。
对标 docs/cc-git-integration.md P1「可直接 spawn git rev-parse/symbolic-ref 缓存」。
"""
import hashlib
import subprocess

_git_cache: dict = {}  # key=(fn, cwd) -> value;fail-open 结果也缓存避免重复 spawn

_GIT_TIMEOUT = 5  # 秒;git 状态查询应极快,超时即视为不可用


def _run_git(args, cwd) -> str | None:
    """跑 git 子进程,返回 stdout(strip)或 None(失败/超时/git 未装)。"""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True,
            timeout=_GIT_TIMEOUT, stdin=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None  # git 未装 / 超时 / cwd 不存在
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def is_git_repo(cwd) -> bool:
    key = ("is_repo", str(cwd))
    if key in _git_cache:
        return _git_cache[key]
    val = _run_git(["rev-parse", "--is-inside-work-tree"], cwd) == "true"
    _git_cache[key] = val
    return val


def get_branch(cwd) -> str | None:
    """当前分支名;detached HEAD 回退短 sha;非仓库/失败 -> None。"""
    key = ("branch", str(cwd))
    if key in _git_cache:
        return _git_cache[key]
    val = _run_git(["symbolic-ref", "--short", "HEAD"], cwd)
    if not val:  # detached HEAD:symbolic-ref 失败,回退短 sha
        val = _run_git(["rev-parse", "--short", "HEAD"], cwd)
    _git_cache[key] = val
    return val


def normalize_remote_url(url) -> str | None:
    """归一化 remote url 为 host/owner/repo(对标 cc normalizeGitRemoteUrl,简化)。

    剥协议(ssh/https/http/git)、剥 git@ 前缀、剥 user@ 凭据、剥尾 .git。
    例:git@github.com:o/r.git 与 https://github.com/o/r.git 都 -> github.com/o/r。
    归一化后用于展示(不泄漏凭据)与 remote hash(项目身份)。
    """
    u = (url or "").strip()
    for proto in ("ssh://", "https://", "http://", "git://"):
        if u.startswith(proto):
            u = u[len(proto):]
            break
    if u.startswith("git@"):
        u = u[4:].replace(":", "/", 1)  # git@host:o/r -> host/o/r
    # 剥 user@host 凭据(https://token@host/... 剥协议后剩 token@host/...)
    head = u.split("/", 1)[0]
    if "@" in head:
        u = u.split("@", 1)[1]
    if u.endswith(".git"):
        u = u[:-4]
    return u or None


def get_remote_url(cwd) -> str | None:
    """origin 的原始 url(可能含凭据,仅内部/算 hash 用;展示用 normalize_remote_url)。"""
    key = ("remote", str(cwd))
    if key in _git_cache:
        return _git_cache[key]
    val = _run_git(["remote", "get-url", "origin"], cwd)
    _git_cache[key] = val
    return val


def get_remote_hash(cwd) -> str | None:
    """归一化 origin url -> sha256[:16](项目身份,对标 cc getRepoRemoteHash)。无 remote -> None。"""
    key = ("remote_hash", str(cwd))
    if key in _git_cache:
        return _git_cache[key]
    norm = normalize_remote_url(get_remote_url(cwd))
    val = hashlib.sha256(norm.encode()).hexdigest()[:16] if norm else None
    _git_cache[key] = val
    return val


def reset_cache():
    """测试用:清缓存(防跨用例残留)。"""
    _git_cache.clear()
