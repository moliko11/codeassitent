from source import Queue
def test_fifo():
    q = Queue()
    q.push(1); q.push(2); q.push(3)
    assert q.pop() == 1
    assert q.pop() == 2
    assert q.pop() == 3
def test_empty():
    assert Queue().pop() is None
