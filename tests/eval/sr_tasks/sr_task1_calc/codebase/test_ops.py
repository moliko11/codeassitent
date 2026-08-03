import pytest
from calc.ops import divide, add, multiply

def test_divide_normal():
    assert divide(10, 2) == 5

def test_divide_zero_raises():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)

def test_other_ops():
    assert add(1, 2) == 3
    assert multiply(3, 4) == 12
