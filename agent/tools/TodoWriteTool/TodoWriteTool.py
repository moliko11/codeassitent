"""TodoWrite 工具:维护任务清单(对标 CC TodoWriteTool,无状态版)。

- 无状态:plan 只活在 messages 里(tool_call + tool_result),不存(对标 CC 存 appState 是为 UI 面板,我们不做)。
- 全量替换:每次传完整 todos 数组(对标 CC)。
- verification nudge:关 3+ 项且无 verify 步骤 -> 注入提示(抄 CC TodoWriteTool.ts:76-86)。
- 依赖阶段 7 的 core/plan.py?否:工具不依赖 Plan 类,只是 todos dict(可独立,见 tools-roadmap §2.1)。
"""
from ..registry import tool

TODO_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "imperative: 'Run tests'"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                    "activeForm": {"type": "string", "description": "present continuous: 'Running tests'"},
                },
                "required": ["content", "status", "activeForm"],
            },
        }
    },
    "required": ["todos"],
}


@tool(
    name="todo_write",
    description="维护任务清单(全量替换)。关 3+ 项且无验证步骤时会提示先验证再收尾。",
    input_schema=TODO_WRITE_SCHEMA,
    mutates_external=False,
)
def todo_write(todos):
    all_done = bool(todos) and all(t.get("status") == "completed" for t in todos)
    # verify 识别:英文 "verif" 或中文 "验证"
    has_verify = any(
        "verif" in (t.get("content", "")).lower() or "验证" in t.get("content", "")
        for t in todos
    )
    base = "Todos updated. 用 todo_list 跟踪进度,保持一个 in_progress。"
    # 抄 CC verification nudge:关 3+ 项且无 verify -> 提示先验证(防模型直接收尾)
    if all_done and len(todos) >= 3 and not has_verify:
        base += (
            "\n\n[提示] 你刚关闭 3+ 任务且无验证步骤。给出最终答案前,请先验证结果"
            "(运行测试/检查输出),不要直接收尾。"
        )
    return base
