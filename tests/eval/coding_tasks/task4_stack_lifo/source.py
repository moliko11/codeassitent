class Stack:
    """后进先出(LIFO)栈。"""
    def __init__(self):
        self.items = []

    def push(self, x):
        self.items.append(x)

    def pop(self):
        """弹出并返回栈顶(最后压入的)元素;空栈返回 None。"""
        if not self.items:
            return None
        return self.items.pop(0)

    def peek(self):
        if not self.items:
            return None
        return self.items[-1]

    def size(self):
        return len(self.items)
