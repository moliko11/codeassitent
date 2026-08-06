class LRUCache:
    """LRU 缓存:容量满时淘汰最久未使用的 key。"""
    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = {}
        self.order = []  # 访问顺序,末尾=最近使用,开头=最久未用

    def get(self, key):
        if key not in self.cache:
            return -1
        self.order.remove(key)
        self.order.append(key)
        return self.cache[key]

    def put(self, key, value):
        if key in self.cache:
            self.cache[key] = value
            return
        if len(self.cache) >= self.capacity:
            evict = self.order.pop(0)
            del self.cache[evict]
        self.cache[key] = value
        self.order.append(key)
