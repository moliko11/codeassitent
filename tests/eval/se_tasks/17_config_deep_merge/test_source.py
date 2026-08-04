from source import merge
def test_flat():
    assert merge({"a":1}, {"b":2}) == {"a":1, "b":2}
def test_nested():
    assert merge({"x":{"a":1}}, {"x":{"b":2}}) == {"x":{"a":1, "b":2}}
def test_override():
    assert merge({"a":1}, {"a":2}) == {"a":2}
