class PostStore:
    def __init__(self):
        self._posts = []

    def save(self, post):
        self._posts.append(post)

    def all(self):
        return list(self._posts)
