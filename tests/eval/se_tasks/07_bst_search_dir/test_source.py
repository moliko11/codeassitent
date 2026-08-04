from source import T, search
def test_found():
    tree = T(5, T(3), T(8))
    assert search(tree, 3) is True
    assert search(tree, 8) is True
def test_not_found():
    tree = T(5, T(3), T(8))
    assert search(tree, 4) is False
def test_left_subtree():
    tree = T(10, T(5, T(1), T(7)), T(15))
    assert search(tree, 1) is True
    assert search(tree, 7) is True
