from source import sum_nested

def test_flat():
    assert sum_nested([1, 2, 3]) == 6

def test_nested():
    assert sum_nested([1, [2, 3], 4]) == 10

def test_deep():
    assert sum_nested([1, [2, [3, 4]], 5]) == 15
