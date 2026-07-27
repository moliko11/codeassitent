"""文件版本链条底座(对标 CC utils/fileHistory.ts)。

track_edit(改前备份)+ make_snapshot(每轮快照,mtime 优化)+ rewind(回滚)。
- null backup 支持回滚新建文件(=删除)。
- mtime 优化跳过未改文件(不做每步全量 copy,IO 不爆炸)。
- MAX_SNAPSHOTS=100,超了丢最老;seq 单调递增不回退。

纯 stdlib,不依赖 tools/core。全同步(CC 的 async 在单 run 无竞争,退化为同步)。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

MAX_SNAPSHOTS = 100
INITIAL_STEP_ID = -1   # 初始 snapshot 的 step_id,代表"第一改之前=原版状态"


@dataclass
class FileBackup:
    """单个文件某版本的备份(对标 CC FileHistoryBackup)。
    backup_file_name=None 表示该版本文件不存在(null backup,新建文件的"原版")。
    """
    backup_file_name: str | None
    version: int
    backup_time: float   # 备份时刻(time.time),用于 mtime 优化比对


@dataclass
class Snapshot:
    """一轮的文件快照:每个 tracked 文件指向其某版本 backup(对标 CC FileHistorySnapshot)。"""
    step_id: int                       # 对标 CC messageId,用 step_index
    tracked: dict[str, FileBackup] = field(default_factory=dict)   # {abs_path -> backup}
    timestamp: float = field(default_factory=time.time)


@dataclass
class FileHistory:
    """文件版本链条(对标 CC FileHistoryState)。

    所有写工具(Edit/Write)在写盘前经 ToolExecutor.before_mutation 钩子调 track_edit;
    每步结束调 make_snapshot;rewind 回滚到某 step。
    snapshot 代表"某 step 改后状态";初始 snapshot(step_id=-1)代表原版。
    """
    backup_root: Path
    snapshots: list[Snapshot] = field(default_factory=list)
    tracked_files: set[str] = field(default_factory=set)
    seq: int = 0                       # 单调递增,不随驱逐回退(对标 CC snapshotSequence)

    def __post_init__(self):
        self.backup_root = Path(self.backup_root)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        # 预建初始 snapshot:track_edit 的"上一个 snapshot"兜底,也是原版的归宿。
        if not self.snapshots:
            self.snapshots.append(Snapshot(step_id=INITIAL_STEP_ID))

    # ---- 备份文件名/路径(对标 CC getBackupFileName:725-731)----
    def _backup_name(self, abs_path: str, version: int) -> str:
        h = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]
        return f"{h}@v{version}"

    def _backup_path(self, backup_name: str) -> Path:
        return self.backup_root / backup_name

    # ---- track_edit:改前备份(对标 CC fileHistoryTrackEdit:86-193)----
    def track_edit(self, file_path: str, step_id: int) -> None:
        """改前备份文件的当前(改前)内容。在 before_mutation 钩子调(写盘前)。

        - 已在最近 snapshot 追踪此文件 -> 跳过(防覆盖 v1,对标 :114-118)。
        - 文件不存在 -> null backup(新建文件的"原版")。
        - track_edit 创建的 backup version 恒为 1(对标 :123);更高 version 由 make_snapshot 建。
        """
        abs_path = str(Path(file_path).resolve())
        most_recent = self.snapshots[-1]
        if abs_path in most_recent.tracked:
            # 已追踪:next make_snapshot 会按 mtime 判断是否新备份,不碰 v1。
            return
        backup = self._create_backup(abs_path, version=1)
        most_recent.tracked[abs_path] = backup
        self.tracked_files.add(abs_path)

    def _create_backup(self, abs_path: str, version: int) -> FileBackup:
        """创建一份 backup。文件不存在 -> null backup(对标 CC createBackup ENOENT 分支:748-798)。
        shutil.copy 复制内容+权限模式但不保留 mtime(backup.mtime=copy 时刻);对标 CC copyFile+chmod
        (:773-797)。不保留 mtime 是关键:让 backup.mtime=copy 时刻,_origin_changed 才能用
        original.mtime < backup.mtime 判断"original 在备份后是否改过"(见下)。"""
        if not Path(abs_path).exists():
            return FileBackup(backup_file_name=None, version=version, backup_time=time.time())
        name = self._backup_name(abs_path, version)
        shutil.copy(abs_path, self._backup_path(name))
        return FileBackup(backup_file_name=name, version=version, backup_time=time.time())

    # ---- make_snapshot:每轮快照(对标 CC fileHistoryMakeSnapshot:198-342)----
    def make_snapshot(self, step_id: int) -> Snapshot:
        """每步结束对所有 tracked 文件快照。mtime 优化:没改的复用上次 backup 引用。
        append 新 snapshot;超 MAX_SNAPSHOTS 丢最老;seq 单调递增。"""
        most_recent = self.snapshots[-1]
        new_tracked: dict[str, FileBackup] = {}
        for tracking_path in self.tracked_files:
            latest = most_recent.tracked.get(tracking_path)
            next_version = (latest.version + 1) if latest else 1
            # 文件不存在(被删了)-> null backup(对标 :241-254)
            if not Path(tracking_path).exists():
                new_tracked[tracking_path] = FileBackup(
                    backup_file_name=None, version=next_version, backup_time=time.time())
                continue
            # mtime 优化:latest 非 null 且文件没改 -> 复用引用,不新增 backup 文件(对标 :257-269)
            if latest and latest.backup_file_name is not None \
                    and not self._origin_changed(tracking_path, latest):
                new_tracked[tracking_path] = latest
                continue
            # 改了 -> 新建 backup(改后内容,对标 :272-275)
            new_tracked[tracking_path] = self._create_backup(tracking_path, next_version)
        # 继承:most_recent 里有但本轮没遍历到的(tracked_files 是全集,基本不触发;保险,对标 :290-297)
        for path, backup in most_recent.tracked.items():
            if path not in new_tracked:
                new_tracked[path] = backup
        snap = Snapshot(step_id=step_id, tracked=new_tracked)
        self.snapshots.append(snap)
        if len(self.snapshots) > MAX_SNAPSHOTS:
            self.snapshots.pop(0)     # 丢最老(对标 :309-311)
        self.seq += 1
        return snap

    def _origin_changed(self, abs_path: str, backup: FileBackup) -> bool:
        """文件相对 backup 是否改了(对标 CC checkOriginFileChanged:600-634)。
        mtime 优化:文件 mtime < backup_time -> 没改(False);mtime 变了读内容比对兜底。"""
        try:
            st = os.stat(abs_path)
        except FileNotFoundError:
            return True                # 文件没了 -> changed
        if backup.backup_file_name is None:
            return True                # 防御:null 走外层,这里视为 changed
        try:
            bst = os.stat(self._backup_path(backup.backup_file_name))
        except FileNotFoundError:
            return True
        if st.st_size != bst.st_size:
            return True                # size 不同 -> changed
        # mtime 优化:original.mtime < backup.mtime(copy 时刻)-> 没改(对标 :665)。
        # 必须比两个文件 mtime(同精度),不能比 mtime vs time.time()(异精度,Windows 误判)。
        if st.st_mtime < bst.st_mtime:
            return False
        # mtime 变了 -> 读内容比对(兜底:Windows 云同步 mtime 变内容没变,对标 :669-672)
        return Path(abs_path).read_bytes() != self._backup_path(backup.backup_file_name).read_bytes()

    # ---- rewind:回滚(对标 CC fileHistoryRewind:347-397 + applySnapshot:537-591)----
    def rewind(self, step_id: int) -> list[str]:
        """回滚到某 step 的 snapshot,返回变更文件路径列表(abs path)。
        null backup -> unlink(删新建文件);有 backup 且内容不同 -> 还原;相同 -> 跳过。"""
        target = None
        for snap in reversed(self.snapshots):   # findLast(对标 :366-368)
            if snap.step_id == step_id:
                target = snap
                break
        if target is None:
            raise ValueError(f"Snapshot for step_id={step_id} not found")
        changed: list[str] = []
        for tracking_path in self.tracked_files:
            target_backup = target.tracked.get(tracking_path)
            if target_backup is not None:
                backup_name = target_backup.backup_file_name        # str | None
            else:
                # target 没追踪此文件(文件在 target 之后才追踪)-> 回退到最早 v1(对标 :547-549)
                found, first_name = self._first_version_name(tracking_path)
                if not found:
                    continue                                         # undefined:跳过(对标 :551-560)
                backup_name = first_name                            # str | None
            if backup_name is None:
                # null backup:文件当时不存在 -> 删除(对标 :562-573)
                p = Path(tracking_path)
                if p.exists():
                    p.unlink()
                    changed.append(tracking_path)
                continue
            # 有 backup:内容不同才还原(对标 :576-582)
            if self._origin_changed(tracking_path, FileBackup(backup_name, 0, 0.0)):
                shutil.copy(self._backup_path(backup_name), tracking_path)
                changed.append(tracking_path)
        return changed

    def _first_version_name(self, tracking_path: str) -> tuple[bool, str | None]:
        """找该文件最早 version(v1)的 backup_file_name(对标 CC getBackupFileNameFirstVersion:847-862)。
        返回 (found, name):found=False=找不到任何版本;found=True + name=None=v1 是 null;found=True + name=str=有 backup。"""
        for snap in self.snapshots:
            b = snap.tracked.get(tracking_path)
            if b is not None and b.version == 1:
                return True, b.backup_file_name
        return False, None

    def can_restore(self, step_id: int) -> bool:
        """是否存在该 step 的 snapshot(对标 CC fileHistoryCanRestore:399-408)。"""
        return any(s.step_id == step_id for s in self.snapshots)
