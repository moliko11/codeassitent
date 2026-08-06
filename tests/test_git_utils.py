"""agent/utils/git.py + prompts._git_info 测试(P1 git 状态注入 prompt)。

不依赖真实 LLM。git 状态查询测试用 tmp git 仓库(subprocess git init);无 git 则 skip
(对标项目「测试不依赖真实 LLM」精神 -- git 状态查询本质要 git,skip 兜底)。
运行(从 code/ 目录,3.12 venv):python -m pytest tests/test_git_utils.py -v
"""
import subprocess

import pytest

from agent.utils import git as gitutil
from agent.utils.git import (normalize_remote_url, is_git_repo, get_branch,
                             get_remote_url, get_remote_hash)
from agent.prompts import _git_info, build_system_prompt
from agent.config.config import AgentConfig


@pytest.fixture(autouse=True)
def _clear_cache():
    """每测试清 git 缓存(防跨用例残留)。"""
    gitutil.reset_cache()
    yield
    gitutil.reset_cache()


@pytest.fixture(autouse=True)
def _isolate_git_discovery(tmp_path, monkeypatch):
    """限制 git 仓库发现不穿透 tmp_path.parent:防 tmp_path 恰在某 git 仓库内时
    污染「非仓库」断言(本机 Temp 在一个 master 分支仓库内)。GIT_CEILING_DIRECTORIES
    让 git 不向上找 .git;tmp_path 自身的 .git(由 _init_repo 建)仍能被发现。"""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _init_repo(path, remote=None):
    """在 path 建 git 仓库(无 commit),可选加 origin remote。"""
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True, capture_output=True)
    if remote:
        subprocess.run(["git", "remote", "add", "origin", remote],
                       cwd=str(path), check=True, capture_output=True)


no_git = pytest.mark.skipif(not _git_available(), reason="git 未安装")


# ─────────────────── normalize_remote_url(纯函数)───────────────────

def test_normalize_remote_ssh():
    assert normalize_remote_url("git@github.com:owner/repo.git") == "github.com/owner/repo"


def test_normalize_remote_https():
    assert normalize_remote_url("https://github.com/owner/repo.git") == "github.com/owner/repo"


def test_normalize_remote_strips_creds():
    """https://token@host/... -> 剥凭据(不泄漏进 prompt)。"""
    assert normalize_remote_url("https://token@github.com/owner/repo") == "github.com/owner/repo"


def test_normalize_remote_ssh_protocol():
    assert normalize_remote_url("ssh://git@github.com/owner/repo.git") == "github.com/owner/repo"


def test_normalize_remote_equivalent():
    """ssh 与 https 同仓库归一化一致(项目身份 hash 据此一致)。"""
    assert normalize_remote_url("git@github.com:o/r.git") == normalize_remote_url("https://github.com/o/r.git")


def test_normalize_remote_none():
    assert normalize_remote_url("") is None
    assert normalize_remote_url(None) is None


# ─────────────────── 状态查询(需 git,skip 兜底)───────────────────

@no_git
def test_is_git_repo_true(tmp_path):
    _init_repo(tmp_path)
    assert is_git_repo(str(tmp_path)) is True


@no_git
def test_is_git_repo_false(tmp_path):
    assert is_git_repo(str(tmp_path)) is False  # 空目录非仓库


@no_git
def test_get_branch_after_init(tmp_path):
    """git init 后无 commit 也能拿默认分支名(symbolic-ref 读 HEAD symref)。"""
    _init_repo(tmp_path)
    assert get_branch(str(tmp_path)) is not None


@no_git
def test_get_branch_non_repo_none(tmp_path):
    assert get_branch(str(tmp_path)) is None


@no_git
def test_remote_url_and_hash(tmp_path):
    _init_repo(tmp_path, remote="git@github.com:owner/repo.git")
    assert get_remote_url(str(tmp_path)) == "git@github.com:owner/repo.git"
    h = get_remote_hash(str(tmp_path))
    assert h is not None and len(h) == 16


@no_git
def test_remote_hash_consistent_across_equivalent_urls(tmp_path):
    """ssh 与 https 同仓库 -> 同 remote hash(归一化后 sha256 一致)。"""
    r1 = tmp_path / "r1"; r1.mkdir(); _init_repo(r1, remote="git@github.com:owner/repo.git")
    r2 = tmp_path / "r2"; r2.mkdir(); _init_repo(r2, remote="https://github.com/owner/repo.git")
    assert get_remote_hash(str(r1)) == get_remote_hash(str(r2))


@no_git
def test_no_remote_returns_none(tmp_path):
    """无 origin remote:get_remote_url/hash 返回 None,不抛。"""
    _init_repo(tmp_path)
    assert get_remote_url(str(tmp_path)) is None
    assert get_remote_hash(str(tmp_path)) is None


# ─────────────────── prompts._git_info / build_system_prompt ───────────────────

@no_git
def test_git_info_in_repo(tmp_path, monkeypatch):
    _init_repo(tmp_path, remote="https://github.com/owner/repo.git")
    monkeypatch.chdir(tmp_path)
    info = _git_info(AgentConfig())
    assert info is not None
    assert "分支:" in info
    assert "github.com/owner/repo" in info  # 归一化 remote(无凭据)


@no_git
def test_git_info_non_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # 空目录
    assert _git_info(AgentConfig()) is None


def test_git_info_disabled():
    """include_git_info=False -> None(短路在 is_git_repo 前,无需 chdir)。"""
    assert _git_info(AgentConfig(include_git_info=False)) is None


@no_git
def test_build_system_prompt_has_git_section(tmp_path, monkeypatch):
    """端到端:在 git 仓库内,build_system_prompt 含「## 仓库」段 + P2 git 历史指导段。"""
    _init_repo(tmp_path, remote="git@github.com:o/r.git")
    monkeypatch.chdir(tmp_path)
    prompt = build_system_prompt(AgentConfig())
    assert "## 仓库" in prompt
    assert "分支:" in prompt
    # P2 静态段:改代码前看 git 历史
    assert "git 历史" in prompt


@no_git
def test_build_system_prompt_no_git_section_when_disabled(tmp_path, monkeypatch):
    """include_git_info=False 时 prompt 不含「## 仓库」段(即便在仓库内)。"""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    prompt = build_system_prompt(AgentConfig(include_git_info=False))
    assert "## 仓库" not in prompt
