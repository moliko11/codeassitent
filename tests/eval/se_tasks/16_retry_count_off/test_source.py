import pytest
from source import retry
def test_success():
    assert retry(lambda: 42, 3) == 42
def test_fail_count():
    calls = [0]
    def fn():
        calls[0] += 1
        raise ValueError("x")
    with pytest.raises(ValueError):
        retry(fn, 3)
    assert calls[0] == 3
def test_second_ok():
    calls = [0]
    def fn():
        calls[0] += 1
        if calls[0] < 2:
            raise ValueError("x")
        return "ok"
    assert retry(fn, 3) == "ok"
