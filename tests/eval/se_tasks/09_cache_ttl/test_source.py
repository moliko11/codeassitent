from source import Cache
def test_hit():
    c = Cache(); c.set("a", 1, 10, 0)
    assert c.get("a", 5) == 1
def test_expired():
    c = Cache(); c.set("a", 1, 10, 0)
    assert c.get("a", 20) is None
def test_miss():
    assert Cache().get("x", 0) is None
