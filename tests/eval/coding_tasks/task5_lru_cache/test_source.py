from source import LRUCache

def test_basic_evict():
    c = LRUCache(2)
    c.put(1, 1); c.put(2, 2)
    assert c.get(1) == 1   # 1 变最近,2 变最久
    c.put(3, 3)            # 淘汰 2
    assert c.get(2) == -1
    assert c.get(3) == 3
    assert c.get(1) == 1

def test_update_value_recency():
    c = LRUCache(2)
    c.put(1, 1); c.put(2, 2)
    c.put(1, 100)          # 更新 1 的值,1 应变最近
    c.put(3, 3)            # 应淘汰 2,不是 1
    assert c.get(2) == -1
    assert c.get(1) == 100
    assert c.get(3) == 3

def test_get_updates_recency():
    c = LRUCache(2)
    c.put(1, 1); c.put(2, 2)
    c.put(1, 1)            # 更新 1(值相同),1 最近
    c.put(3, 3)            # 淘汰 2
    assert c.get(1) == 1
    assert c.get(2) == -1
