class Cache:
    """带 TTL 的缓存。get 时过期应返回 None。"""
    def __init__(self):
        self.store = {}
    def set(self, k, v, ttl, now):
        self.store[k] = (v, now + ttl)
    def get(self, k, now):
        if k in self.store:
            return self.store[k][0]
        return None
