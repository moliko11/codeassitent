"""Bash 工具:执行 shell 命令,返回 stdout/stderr/exit_code。

对标 CC BashTool:执行 + 超时 + 后台。简化(见 CLAUDE.md impl-style):
- 不做沙箱(留 TODO,对标 CC SandboxManager);只做超时。
- 不接 trackEdit(命令改哪些文件拿不到,是工具体系边界;CC 也不靠 Bash 追踪编辑)。
- git 命令的安全门禁不在本工具内,而在 before_tool Guardrail(GitSafetyGuard):
  CC 对每条 git 命令做白名单 + 多层门禁(见 docs/cc-reference/cc-git-integration.md),
  非简单"靠 git"。本工具只负责执行,git 只读/写/硬拦判定见 guardrails/git_safety.py。
- 失败命令(exit_code!=0)不抛异常,返回 exit_code 让 LLM 看 stderr 自行调整。
- 超时抛 ToolTimeoutError(可重试,对标阶段4 _run_with_timeout)。
- mutates_external=True 但 before_mutation 回调对 Bash 跳过(无 file_path,见 commit 4 接线)。
"""
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


@tool(
    name="bash",
    description="执行 shell 命令,返回 {stdout, stderr, exit_code}。失败不抛(返回 exit_code);超时抛超时错误。",
    input_schema=BASH_SCHEMA,
    mutates_external=True,   # 命令可能改文件;但 before_mutation 对 Bash 跳过(无 file_path)
)
def bash(command, timeout=None):
    timeout = timeout if timeout is not None else t("bash.default_timeout", 30)  # tools.yaml,缺省 30
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        raise ToolTimeoutError(f"命令执行超时({timeout}s)")
