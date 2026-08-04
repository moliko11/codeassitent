from source import split_n
def test_limit():
    assert split_n("a,b,c,d", ",", 1) == ["a", "b,c,d"]
def test_limit2():
    assert split_n("a,b,c", ",", 2) == ["a", "b", "c"]
def test_no_sep():
    assert split_n("abc", ",", 1) == ["abc"]
