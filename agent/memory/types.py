# Memory 类型与记录(对齐 cc memdir/memoryTypes.ts)
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# 四类型:不可从项目派生的信息才存(对齐 cc WHAT_NOT_TO_SAVE_SECTION)
MEMORY_TYPES = ("user", "feedback", "project", "reference")


@dataclass
class MemoryRecord:
    """一条长期记忆(对应一个 md 文件)。"""
    name: str
    description: str           # 一句话,索引行 + 召回判断相关性用
    type: str                  # user/feedback/project/reference
    content: str               # 正文
    path: Optional[Path] = None