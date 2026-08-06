class Node:
    def __init__(self, val, nxt=None):
        self.val = val
        self.next = nxt

def insert_after(node, val):
    """在 node 之后插入新节点。"""
    new = Node(val)
    new.next = node.next
    node.next = new.next
    return new
