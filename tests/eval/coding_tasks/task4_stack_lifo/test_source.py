from source import Stack

def test_push_pop_lifo():
    s = Stack()
    s.push(1); s.push(2); s.push(3)
    assert s.pop() == 3
    assert s.pop() == 2
    assert s.pop() == 1

def test_peek_does_not_pop():
    s = Stack()
    s.push(1); s.push(2)
    assert s.peek() == 2
    assert s.size() == 2

def test_empty():
    s = Stack()
    assert s.pop() is None
    assert s.peek() is None
    assert s.size() == 0

def test_interleaved():
    s = Stack()
    s.push("a"); s.push("b")
    assert s.pop() == "b"
    s.push("c")
    assert s.pop() == "c"
    assert s.pop() == "a"
    assert s.size() == 0
