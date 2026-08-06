from source import max_val
def test_max_pos():
    assert max_val([1, 5, 3]) == 5
def test_max_all_neg():
    assert max_val([-1, -5, -3]) == -1
