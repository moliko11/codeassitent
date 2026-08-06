from source import Node, insert_after
def test_insert():
    tail = Node("tail")
    head = Node("head", tail)
    new = insert_after(head, "mid")
    assert head.next.val == "mid"
    assert new.next.val == "tail"
def test_insert_at_end():
    head = Node("head")
    new = insert_after(head, "x")
    assert head.next.val == "x"
    assert new.next is None
