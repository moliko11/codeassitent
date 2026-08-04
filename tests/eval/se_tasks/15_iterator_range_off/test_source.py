from source import RangeN
def test_range():
    assert list(RangeN(3)) == [0, 1, 2]
def test_empty():
    assert list(RangeN(0)) == []
def test_one():
    assert list(RangeN(1)) == [0]
