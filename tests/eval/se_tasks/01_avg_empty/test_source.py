from source import avg
def test_avg_normal():
    assert avg([1, 2, 3]) == 2
def test_avg_empty():
    assert avg([]) == 0
