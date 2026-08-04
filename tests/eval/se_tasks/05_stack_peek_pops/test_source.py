from source import Stack
def test_peek_no_pop():
    s = Stack()
    s.push(1); s.push(2)
    assert s.peek() == 2
    assert s.size() == 2 if hasattr(s,'size') else len(s.items) == 2
def test_pop():
    s = Stack(); s.push(1)
    assert s.pop() == 1
