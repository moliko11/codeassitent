# MemoryStore -- 文件存储的长期记忆(对齐 cc memdir/)
#
# 核心设计(对齐 cc):
# - 一个 memory 一个 md 文件(frontmatter + 正文)
# - MEMORY.md 是索引(一行指针 - [Title](file.md) - hook),常驻系统提示,不含 memory 正文
# - 写入两步:写 md 文件 + 更新 MEMORY.md 索引(cc 让模型手动两步,本版由 write() 自动完成)
# - recall 召回 memory 正文(不召回索引已含的标题),按 query 关键词匹配 top_k
#
# 简化:recall 用关键词匹配(cc 用 LLM-as-selector);无 extractMemories 后台提取(cc 用 forked agent)
from __future__ import annotations

import re
from pathlib import Path

from .types import MemoryRecord, MEMORY_TYPES

INDEX_FILE = "MEMORY.md"


class MemoryStore:
    def __init__(self, dir_path, recall_top_k: int = 5, index_file: str = INDEX_FILE):
        # recall_top_k / index_file 走 memory.yaml(缺省 5 / MEMORY.md)；builder 注入召回
        # 走 ContextBuilder.memory_recall_top_k(context.yaml),是两个独立旋钮(历史遗留)。
        self.dir = Path(dir_path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.recall_top_k = recall_top_k
        self.index_file = index_file

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.md"

    def _index_path(self) -> Path:
        # 索引文件(默认 MEMORY.md),常驻系统提示,不含 memory 正文
        return self.dir / self.index_file

    def write(self, name, description, type, content) -> Path:
        """写一条 memory:写 md 文件 + 更新 MEMORY.md 索引(两步,对齐 cc)。

        同名 memory 覆盖 md 文件 + 更新索引行(不重复)。
        """
        if type not in MEMORY_TYPES:
            raise ValueError(f"type 必须是 {MEMORY_TYPES},得到 {type}")
        # Step 1: 写 md 文件
        path = self._path(name)
        text = (
            f"---\nname: {name}\ndescription: {description}\ntype: {type}\n---\n\n"
            f"{content}\n"
        )
        path.write_text(text, encoding="utf-8")
        # Step 2: 更新 MEMORY.md 索引(对齐 cc 两步写)
        self._upsert_index(name, description)
        return path

    def read(self, name) -> MemoryRecord:
        return self._parse(self._path(name))

    def list(self) -> list[MemoryRecord]:
        return [self._parse(p) for p in self.dir.glob("*.md") if p.name != self.index_file]

    def forget(self, name) -> bool:
        """删 md 文件 + 从 MEMORY.md 索引移除该行。"""
        p = self._path(name)
        if not p.exists():
            return False
        p.unlink()
        self._remove_from_index(name)
        return True

    def read_index(self) -> str:
        """读 MEMORY.md 索引内容(注入系统提示用)。无则空串。"""
        p = self._index_path()
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def recall(self, query: str, top_k: int | None = None) -> list[MemoryRecord]:
        """关键词匹配召回 memory 正文(不召回索引已含的标题)。

        对齐 cc findRelevantMemories 的"按 query 选相关 memory",但用关键词匹配
        代替 LLM-as-selector(不引依赖、可单测)。无命中返回空。
        top_k 缺省用 self.recall_top_k(memory.yaml,缺省 5)。
        """
        if top_k is None:
            top_k = self.recall_top_k
        records = self.list()
        if not records:
            return []
        q = query.lower()
        tokens = re.findall(r"[a-z]+|[一-鿿]{2}", q)
        if not tokens:
            return []

        def score(r):
            text = (r.name + " " + r.description + " " + r.content).lower()
            return sum(text.count(t) for t in tokens)

        scored = [(r, score(r)) for r in records]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, s in scored if s > 0][:top_k]

    # ---- 索引维护 ----

    def _upsert_index(self, name: str, description: str):
        """更新或插入一条索引行(同名更新 description,不重复)。"""
        p = self._index_path()
        lines = []
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if f"]({name}.md)" in line:
                    continue  # 跳过旧的同名行,下面追加新的
                lines.append(line)
        lines.append(f"- [{name}]({name}.md) - {description}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _remove_from_index(self, name: str):
        p = self._index_path()
        if not p.exists():
            return
        lines = [l for l in p.read_text(encoding="utf-8").splitlines()
                 if f"]({name}.md)" not in l]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _parse(self, path: Path) -> MemoryRecord:
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n\n?(.*)$", text, re.DOTALL)
        if not m:
            return MemoryRecord(name=path.stem, description="", type="reference",
                                content=text, path=path)
        meta_text, content = m.group(1), m.group(2)
        meta = {}
        for line in meta_text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return MemoryRecord(
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            type=meta.get("type", "reference"),
            content=content,
            path=path,
        )