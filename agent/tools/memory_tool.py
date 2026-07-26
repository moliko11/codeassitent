# save_memory 工具:模型调用写长期记忆
#
# 对齐 cc:cc 让模型用 Write/FileEdit 手动两步(写 md + 更新 MEMORY.md 索引)。
# 本版因无通用 Write 工具,用 save_memory 专用工具一步完成 write()(内部自动两步。
# 标注:进阶可上通用 Write 工具,让模型手动两步(更贴 cc)。
from .defs import Tool, ToolSpec

SAVE_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "记忆名(kebab-case,作文件名)"},
        "description": {"type": "string", "description": "一句话描述,作 MEMORY.md 索引行 + 召回相关性判断"},
        "type": {"type": "string", "enum": ["user", "feedback", "project", "reference"],
                 "description": "user=用户画像/feedback=用户反馈/project=项目背景/reference=外部资源"},
        "content": {"type": "string", "description": "记忆正文(feedback/project 建议 Why+How to apply)"},
    },
    "required": ["name", "description", "type", "content"],
}


def make_save_memory_tool(store):
    """造一个 save_memory 工具,closure 捕获 memory_store。"""
    def handler(name, description, type, content):
        path = store.write(name=name, description=description, type=type, content=content)
        return {"ok": True, "name": name, "path": str(path),
                "note": "已写 memory 文件并更新 MEMORY.md 索引"}
    return Tool(
        tool_spec=ToolSpec(
            name="save_memory",
            description=(
                "保存一条长期记忆(跨对话保留)。工具自动写 memory 文件并更新 MEMORY.md 索引。"
                "何时用:学到用户偏好/反馈、项目背景、外部资源引用时。"
                "何时不写:代码/架构/git/文件结构(可从项目派生)不存;已存在的先更新而非重复保存。"
            ),
            input_schema=SAVE_MEMORY_SCHEMA,
        ),
        handler=handler,
    )