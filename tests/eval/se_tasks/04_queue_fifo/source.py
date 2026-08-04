class Queue:
    """FIFO 队列。"""
    def __init__(self):
        self.q = []
    def push(self, x):
        self.q.append(x)
    def pop(self):
        if not self.q:
            return None
        return self.q.pop()
