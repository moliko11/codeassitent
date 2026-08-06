class Node:
    def __init__(self, val, nxt=None):
        self.val = val
        self.next = nxt

def insert_after(node, val):
    new = Node(val)
    new.next = node.next
    node.next = new
    return new
