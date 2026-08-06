class T:
    def __init__(self, val, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def search(node, x):
    if node is None:
        return False
    if x == node.val:
        return True
    if x < node.val:
        return search(node.left, x)
    return search(node.right, x)
