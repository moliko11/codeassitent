# tests/conftest.py - 共享测试夹具
#
# 去重:原各测试文件各写一份 _tmp_persist_root(7 份相同逻辑)。这里收成一份 autouse,
# 覆盖全部测试(PERSIST_ROOT 指到 tmp_path,测试落盘不污染 code/persist)。
import pytest

import agent.persist.paths as paths


@pytest.fixture(autouse=True)
def _tmp_persist_root(tmp_path, monkeypatch):
    """PERSIST_ROOT 指到 tmp_path,测试落盘不污染 code/persist。autouse 覆盖全部测试。"""
    monkeypatch.setattr(paths, "PERSIST_ROOT", tmp_path / "runs")
