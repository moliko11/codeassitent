from source import sum_range

def test_inclusive_end():
    assert sum_range(1, 5) == 15  # 1+2+3+4+5

def test_single():
    assert sum_range(1, 1) == 1

def test_same_end():
    assert sum_range(5, 5) == 5
