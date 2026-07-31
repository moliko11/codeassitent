# core/workspace.py - 工作空间与路径权限(阶段8 执行层,对齐 workspace-design.md)
# workspace 是 Runtime 一等公民(非裸 os.getcwd);路径权限是安全层(写操作强制 allows)。
# 对比 CC:CC 用 originalCwd/cwd/projectRoot 三层 + validatePath 5步 + pathInAllowedPath;
# 我们先做单层 root + additional_dirs + allows(resolve+parents 判包含)。
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Workspace:
    """工作空间:路径解析 + 权限校验。

    - root:启动目录(resolve 后,解 symlink,= originalCwd)
    - additional_dirs:--add-dir 加的额外允许目录
    - resolve(p):相对 root 解析 + 展开 ~ + resolve()(解 symlink,防 ../ 逃逸)
    - allows(p):resolve 后判 p 在 {root}∪additional_dirs 内(用 parents,非 startsWith)
    """
    root: Path
    additional_dirs: list[Path] = field(default_factory=list)

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        self.additional_dirs = [Path(d).resolve() for d in self.additional_dirs]

    def resolve(self, p: str | Path) -> Path:
        """相对 root 解析 + 展开 ~ + resolve()(解 symlink)。"""
        path = Path(p).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()

    def allows(self, p: str | Path) -> bool:
        """p 是否在允许集 {root}∪additional_dirs 内。

        resolve 后判包含:p == d 或 d in p.parents(等价 CC posix.relative 判包含)。
        用 parents 而非 startsWith:防 "/allowed" startsWith "/allow" 误判 + symlink 逃逸。
        """
        rp = self.resolve(p)
        allowed = [self.root] + self.additional_dirs
        return any(rp == d or d in rp.parents for d in allowed)
