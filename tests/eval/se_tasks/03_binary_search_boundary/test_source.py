from source import bsearch
def test_found():
    assert bsearch([1,2,3,4,5], 3) == 2
def test_last():
    assert bsearch([1,2,3,4,5], 5) == 4
def test_first():
    assert bsearch([1,2,3,4,5], 1) == 0
def test_not_found():
    assert bsearch([1,2,3], 9) == -1
