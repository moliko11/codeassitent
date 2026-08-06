class Door:
    def __init__(self):
        self.state = "closed"
    def open(self):
        if self.state == "open":
            raise ValueError("already open")
        self.state = "open"
    def close(self):
        self.state = "closed"
