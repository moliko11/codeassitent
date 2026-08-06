class Post:
    def __init__(self, title, content, tags=None):
        self.title = title
        self.content = content
        self.tags = tags or []
