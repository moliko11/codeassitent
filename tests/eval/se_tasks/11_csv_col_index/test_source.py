from source import get_col
def test_col0():
    assert get_col("a,b,c", 0) == "a"
def test_col1():
    assert get_col("a,b,c", 1) == "b"
def test_col2():
    assert get_col("a,b,c", 2) == "c"
