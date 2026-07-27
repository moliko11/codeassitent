"""工具间共享状态(对标 CC readFileState + fileHistory 引用)。

模块级单例:
- read_file_state:Read 工具读后写,Edit/Write 校验先读后改 + 陈旧检测。
- file_history:由 agentloop 按 run_id 初始化 FileHistory 后注入(commit 4 接线)。

有先例:阶段4 builtin.sent_emails 是模块级全局。单 run 够用;TODO 多 run 并发挂 RuntimeContext。
"""
from dataclasses import dataclass


@dataclass
class ReadRecord:
    """读时刻的文件快照(对标 CC readFileState[path])。"""
    content: str
    mtime: float              # 读时刻的文件 mtime(Edit 陈旧检测比对)
    is_partial: bool = False  # offset/limit 读了部分 -> Edit 拒绝(对标 CC isPartialView)


# 模块级全局(跨工具共享)
read_file_state: dict[str, ReadRecord] = {}
file_history = None           # 由 agentloop 注入 FileHistory 实例(commit 4)
current_step_id: int = 0      # 当前 step_index,before_mutation 回调读它做 track_edit 的 step_id(commit 4)
model_adapter = None          # 步3 WebFetch 用(调 LLM 提取),agentloop 注入


def reset():
    """测试用:清空模块级状态,防测试间残留(任务文档测试前置要求)。"""
    read_file_state.clear()
    global file_history, current_step_id, model_adapter
    file_history = None
    current_step_id = 0
    model_adapter = None
