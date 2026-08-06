class Cache:
    def __init__(self):
        self.store = {}
    def set(self, k, v, ttl, now):
        self.store[k] = (v, now + ttl)
    def get(self, k, now):
        if k in self.store:
            v, expire = self.store[k]
            if now > expire:
                del self.store[k]
                return None
            return v
        return None
