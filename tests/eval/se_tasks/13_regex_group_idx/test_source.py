from source import extract_name
def test_name():
    assert extract_name("abc-123") == "abc"
def test_other():
    assert extract_name("foo-456") == "foo"
def test_no_match():
    assert extract_name("nope") is None
