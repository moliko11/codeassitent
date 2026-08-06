class Door:
    """门状态机:closed->open->closed。不能从 open 再 open。"""
    def __init__(self):
        self.state = "closed"
    def open(self):
        self.state = "open"
    def close(self):
        self.state = "closed"
