"""Bash 工具:执行 shell 命令,返回 stdout/stderr/exit_code。

对标 CC BashTool:执行 + 超时 + 后台。简化(见 CLAUDE.md impl-style):
- 不做沙箱(留 TODO,对标 CC SandboxManager);只做超时。
- 不接 trackEdit(命令改哪些文件拿不到,是工具体系边界;CC 也不靠 Bash 追踪编辑)。
- git 命令的安全门禁不在本工具内,而在 ToolExecutor.can_use_tool(git 分类 + 写命令走 confirmer):
  CC 对每条 git 命令做白名单 + 多层门禁(见 docs/cc-reference/cc-git-integration.md),
  非简单"靠 git"。本工具只负责执行,git 只读/写/硬拦判定见 guardrails/git_safety.py。
- 失败命令(exit_code!=0)不抛异常,返回 exit_code 让 LLM 看 stderr 自行调整。
- 超时抛 ToolTimeoutError(可重试,对标阶段4 _run_with_timeout)。
- mutates_external=True 但 before_mutation 回调对 Bash 跳过(无 file_path,见 commit 4 接线)。
"""
import os
import signal
import subprocess

from ..registry import tool
from ..settings import t
from ...core.errors import ToolTimeoutError

BASH_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "shell 命令"},
        "timeout": {"type": "number", "description": "超时秒数,默认 30"},
    },
    "required": ["command"],
}


def _kill_tree(proc: subprocess.Popen):
    """杀掉整个进程树(修复 Windows bug:naive subprocess.run 超时只杀 cmd.exe,
    py 子进程存活且握着 stdout/stderr 管道 -> 内部 communicate() 挂到子进程结束,
    整个 agent 阻塞到 step_timeout 才恢复)。Windows 用 taskkill /T(杀树),
    POSIX 用 killpg(新会话组)。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, text=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def _run_command(command: str, timeout: float):
    """执行命令,超时可靠地杀整树并返回,不让子进程握着管道挂住调用方。

    - Popen + CREATE_NEW_PROCESS_GROUP(Windows)/start_new_session(POSIX):进程独立成组,
      _kill_tree 才能整树杀(cmd 的子进程 / 孙进程)。
    - communicate(timeout=) 超时 -> 整树杀 -> 再 communicate 收尾(树已死,管道关闭,不挂)。
    """
    # 注:capture_output 是 subprocess.run 的糖,Popen 需显式 stdout/stderr=PIPE
    kwargs = {"shell": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # 整树杀后立即抛,不做 drain:子进程可能仍握管道,再 communicate 会挂(Windows)。
        # taskkill /T 已杀树,管道由 OS 收尾,agent 在 timeout 秒内解阻。
        _kill_tree(proc)
        raise ToolTimeoutError(f"命令执行超时({timeout}s)")
    return stdout, stderr, proc.returncode


@tool(
    name="bash",
    description="执行 shell 命令,返回 {stdout, stderr, exit_code}。失败不抛(返回 exit_code);超时抛超时错误。",
    input_schema=BASH_SCHEMA,
    mutates_external=True,   # 命令可能改文件;但 before_mutation 对 Bash 跳过(无 file_path)
)
def bash(command, timeout=None):
    timeout = timeout if timeout is not None else t("bash.default_timeout", 30)  # tools.yaml,缺省 30
    stdout, stderr, exit_code = _run_command(command, timeout)
    return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
