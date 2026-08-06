"""生成 20 条较复杂的软件工程任务(逻辑/状态/边界 bug,非 typo)。
每条: source.py(有bug) + test_source.py + solution.py + task.md。
跑: python tests/eval/generate_se_tasks.py
"""
import os, textwrap

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "se_tasks")

# (name, source_bug, test, solution, desc)
TASKS = [
("01_avg_empty",
'''def avg(nums):
    """返回平均值。"""
    return sum(nums) / len(nums)
''',
'''from source import avg
def test_avg_normal():
    assert avg([1, 2, 3]) == 2
def test_avg_empty():
    assert avg([]) == 0
''',
'''def avg(nums):
    if not nums:
        return 0
    return sum(nums) / len(nums)
''',
"avg 没处理空列表(除零)。空列表应返回 0。"),
("02_max_init_neg",
'''def max_val(nums):
    """返回最大值。"""
    m = 0
    for n in nums:
        if n > m:
            m = n
    return m
''',
'''from source import max_val
def test_max_pos():
    assert max_val([1, 5, 3]) == 5
def test_max_all_neg():
    assert max_val([-1, -5, -3]) == -1
''',
'''def max_val(nums):
    m = float("-inf")
    for n in nums:
        if n > m:
            m = n
    return m
''',
"max 初始化为 0,全负数列返回 0(错)。应用 -inf。"),
("03_binary_search_boundary",
'''def bsearch(arr, x):
    """二分搜索,返回索引或 -1。"""
    lo, hi = 0, len(arr) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == x:
            return mid
        elif arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
'''from source import bsearch
def test_found():
    assert bsearch([1,2,3,4,5], 3) == 2
def test_last():
    assert bsearch([1,2,3,4,5], 5) == 4
def test_first():
    assert bsearch([1,2,3,4,5], 1) == 0
def test_not_found():
    assert bsearch([1,2,3], 9) == -1
''',
'''def bsearch(arr, x):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == x:
            return mid
        elif arr[mid] < x:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''',
"二分循环用 lo<hi,漏 lo==hi(最后元素找不到)。应 lo<=hi。"),
("04_queue_fifo",
'''class Queue:
    """FIFO 队列。"""
    def __init__(self):
        self.q = []
    def push(self, x):
        self.q.append(x)
    def pop(self):
        if not self.q:
            return None
        return self.q.pop()
''',
'''from source import Queue
def test_fifo():
    q = Queue()
    q.push(1); q.push(2); q.push(3)
    assert q.pop() == 1
    assert q.pop() == 2
    assert q.pop() == 3
def test_empty():
    assert Queue().pop() is None
''',
'''class Queue:
    def __init__(self):
        self.q = []
    def push(self, x):
        self.q.append(x)
    def pop(self):
        if not self.q:
            return None
        return self.q.pop(0)
''',
"Queue.pop 用 pop()(LIFO),应 pop(0)(FIFO)。"),
("05_stack_peek_pops",
'''class Stack:
    """LIFO 栈。"""
    def __init__(self):
        self.items = []
    def push(self, x):
        self.items.append(x)
    def pop(self):
        if not self.items:
            return None
        return self.items.pop()
    def peek(self):
        if not self.items:
            return None
        return self.items.pop()
''',
'''from source import Stack
def test_peek_no_pop():
    s = Stack()
    s.push(1); s.push(2)
    assert s.peek() == 2
    assert s.size() == 2 if hasattr(s,'size') else len(s.items) == 2
def test_pop():
    s = Stack(); s.push(1)
    assert s.pop() == 1
''',
'''class Stack:
    def __init__(self):
        self.items = []
    def push(self, x):
        self.items.append(x)
    def pop(self):
        if not self.items:
            return None
        return self.items.pop()
    def peek(self):
        if not self.items:
            return None
        return self.items[-1]
''',
"peek 误用 pop()(弹出了元素),应 [-1] 只看不弹。"),
("06_linked_list_insert",
'''class Node:
    def __init__(self, val, nxt=None):
        self.val = val
        self.next = nxt

def insert_after(node, val):
    """在 node 之后插入新节点。"""
    new = Node(val)
    new.next = node.next
    node.next = new.next
    return new
''',
'''from source import Node, insert_after
def test_insert():
    tail = Node("tail")
    head = Node("head", tail)
    new = insert_after(head, "mid")
    assert head.next.val == "mid"
    assert new.next.val == "tail"
def test_insert_at_end():
    head = Node("head")
    new = insert_after(head, "x")
    assert head.next.val == "x"
    assert new.next is None
''',
'''class Node:
    def __init__(self, val, nxt=None):
        self.val = val
        self.next = nxt

def insert_after(node, val):
    new = Node(val)
    new.next = node.next
    node.next = new
    return new
''',
"insert_after 漏 node.next=new,新节点没接上。"),
("07_bst_search_dir",
'''class T:
    def __init__(self, val, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def search(node, x):
    """BST 搜索。"""
    if node is None:
        return False
    if x == node.val:
        return True
    if x < node.val:
        return search(node.right, x)
    return search(node.left, x)
''',
'''from source import T, search
def test_found():
    tree = T(5, T(3), T(8))
    assert search(tree, 3) is True
    assert search(tree, 8) is True
def test_not_found():
    tree = T(5, T(3), T(8))
    assert search(tree, 4) is False
def test_left_subtree():
    tree = T(10, T(5, T(1), T(7)), T(15))
    assert search(tree, 1) is True
    assert search(tree, 7) is True
''',
'''class T:
    def __init__(self, val, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def search(node, x):
    if node is None:
        return False
    if x == node.val:
        return True
    if x < node.val:
        return search(node.left, x)
    return search(node.right, x)
''',
"BST 搜索方向反了(x<val 应搜左,却搜右)。"),
("08_graph_dfs_cycle",
'''def dfs(graph, start):
    """DFS,返回访问过的节点集。有环图不能无限递归。"""
    visited = set()
    def go(n):
        visited.add(n)
        for nb in graph.get(n, []):
            go(nb)
    go(start)
    return visited
''',
'''from source import dfs
def test_simple():
    assert dfs({1:[2,3], 2:[], 3:[]}, 1) == {1,2,3}
def test_cycle():
    g = {1:[2], 2:[3], 3:[1]}
    assert dfs(g, 1) == {1,2,3}
def test_disconnected():
    assert dfs({1:[2], 2:[], 3:[]}, 1) == {1,2}
''',
'''def dfs(graph, start):
    visited = set()
    def go(n):
        visited.add(n)
        for nb in graph.get(n, []):
            if nb not in visited:
                go(nb)
    go(start)
    return visited
''',
"DFS 没检查 nb in visited,有环图无限递归。"),
("09_cache_ttl",
'''class Cache:
    """带 TTL 的缓存。get 时过期应返回 None。"""
    def __init__(self):
        self.store = {}
    def set(self, k, v, ttl, now):
        self.store[k] = (v, now + ttl)
    def get(self, k, now):
        if k in self.store:
            return self.store[k][0]
        return None
''',
'''from source import Cache
def test_hit():
    c = Cache(); c.set("a", 1, 10, 0)
    assert c.get("a", 5) == 1
def test_expired():
    c = Cache(); c.set("a", 1, 10, 0)
    assert c.get("a", 20) is None
def test_miss():
    assert Cache().get("x", 0) is None
''',
'''class Cache:
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
''',
"Cache.get 没查 TTL 过期,过期仍返回旧值。"),
("10_split_n_limit",
'''def split_n(s, sep, n):
    """按 sep 分割,最多分 n 段(类似 str.split(sep, n))。"""
    return s.split(sep)
''',
'''from source import split_n
def test_limit():
    assert split_n("a,b,c,d", ",", 1) == ["a", "b,c,d"]
def test_limit2():
    assert split_n("a,b,c", ",", 2) == ["a", "b", "c"]
def test_no_sep():
    assert split_n("abc", ",", 1) == ["abc"]
''',
'''def split_n(s, sep, n):
    return s.split(sep, n)
''',
"split_n 没传 n 限制次数,全分了。"),
("11_csv_col_index",
'''def get_col(row, idx):
    """取 CSV 行第 idx 列(0-based)。"""
    return row.split(",")[idx + 1]
''',
'''from source import get_col
def test_col0():
    assert get_col("a,b,c", 0) == "a"
def test_col1():
    assert get_col("a,b,c", 1) == "b"
def test_col2():
    assert get_col("a,b,c", 2) == "c"
''',
'''def get_col(row, idx):
    return row.split(",")[idx]
''',
"get_col 索引 +1 错位(取了下一列)。"),
("12_date_diff_abs",
'''from datetime import date
def days_between(d1, d2):
    """返回两个日期相差天数(非负)。"""
    return (d2 - d1).days
''',
'''from datetime import date
from source import days_between
def test_order1():
    assert days_between(date(2026,1,1), date(2026,1,5)) == 4
def test_order2():
    assert days_between(date(2026,1,5), date(2026,1,1)) == 4
def test_same():
    assert days_between(date(2026,1,1), date(2026,1,1)) == 0
''',
'''from datetime import date
def days_between(d1, d2):
    return abs((d2 - d1).days)
''',
"days_between 没取 abs,d1>d2 时返回负数。"),
("13_regex_group_idx",
'''import re
def extract_name(s):
    """从 'name-123' 格式提取 name 部分。"""
    m = re.search(r"(\w+)-(\d+)", s)
    if m:
        return m.group(2)
    return None
''',
'''from source import extract_name
def test_name():
    assert extract_name("abc-123") == "abc"
def test_other():
    assert extract_name("foo-456") == "foo"
def test_no_match():
    assert extract_name("nope") is None
''',
'''import re
def extract_name(s):
    m = re.search(r"(\w+)-(\d+)", s)
    if m:
        return m.group(1)
    return None
''',
"extract_name 取了 group(2)(数字),应 group(1)(name)。"),
("14_sum_nested",
'''def sum_nested(lst):
    total = 0
    for x in lst:
        if isinstance(x, list):
            total += x
        else:
            total += x
    return total
''',
'''from source import sum_nested

def test_flat():
    assert sum_nested([1, 2, 3]) == 6

def test_nested():
    assert sum_nested([1, [2, 3], 4]) == 10

def test_deep():
    assert sum_nested([1, [2, [3, 4]], 5]) == 15
''',
'''def sum_nested(lst):
    total = 0
    for x in lst:
        if isinstance(x, list):
            total += sum_nested(x)
        else:
            total += x
    return total
''',
"sum_nested 没递归处理嵌套 list(直接 += list 报 TypeError)。应递归求和。"),
("15_iterator_range_off",
'''class RangeN:
    """迭代 0..n-1。"""
    def __init__(self, n):
        self.i = 0
        self.n = n
    def __iter__(self):
        return self
    def __next__(self):
        self.i += 1
        if self.i > self.n:
            raise StopIteration
        return self.i
''',
'''from source import RangeN
def test_range():
    assert list(RangeN(3)) == [0, 1, 2]
def test_empty():
    assert list(RangeN(0)) == []
def test_one():
    assert list(RangeN(1)) == [0]
''',
'''class RangeN:
    def __init__(self, n):
        self.i = 0
        self.n = n
    def __iter__(self):
        return self
    def __next__(self):
        if self.i >= self.n:
            raise StopIteration
        v = self.i
        self.i += 1
        return v
''',
"RangeN 先 +1 再返回,返回 1..n(漏 0)。应先返回再 +1。"),
("16_retry_count_off",
'''def retry(fn, times):
    """重试 fn 最多 times 次,全失败返回最后一次异常。"""
    last = None
    for i in range(times - 1):
        try:
            return fn()
        except Exception as e:
            last = e
    raise last
''',
'''import pytest
from source import retry
def test_success():
    assert retry(lambda: 42, 3) == 42
def test_fail_count():
    calls = [0]
    def fn():
        calls[0] += 1
        raise ValueError("x")
    with pytest.raises(ValueError):
        retry(fn, 3)
    assert calls[0] == 3
def test_second_ok():
    calls = [0]
    def fn():
        calls[0] += 1
        if calls[0] < 2:
            raise ValueError("x")
        return "ok"
    assert retry(fn, 3) == "ok"
''',
'''def retry(fn, times):
    last = None
    for i in range(times):
        try:
            return fn()
        except Exception as e:
            last = e
    raise last
''',
"retry range(times-1) 少重试一次(应 times 次)。"),
("17_config_deep_merge",
'''def merge(a, b):
    """深合并两个配置 dict(嵌套 dict 递归合并,非 dict 覆盖)。"""
    return {**a, **b}
''',
'''from source import merge
def test_flat():
    assert merge({"a":1}, {"b":2}) == {"a":1, "b":2}
def test_nested():
    assert merge({"x":{"a":1}}, {"x":{"b":2}}) == {"x":{"a":1, "b":2}}
def test_override():
    assert merge({"a":1}, {"a":2}) == {"a":2}
''',
'''def merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out
''',
"merge 用 {**a,**b} 浅合并,嵌套 dict 被整个覆盖。应递归。"),
("18_pipeline_order",
'''def double(xs):
    return [x*2 for x in xs]
def filter_even(xs):
    return [x for x in xs if x % 2 == 0]
def pipeline(xs):
    """先翻倍再过滤偶数。"""
    return filter_even(double(xs))
''',
'''from source import pipeline
def test_pipeline():
    # [1,2,3] -> double [2,4,6] -> even [2,4,6]
    assert pipeline([1,2,3]) == [2,4,6]
def test_pipeline2():
    # [1,3,5] -> double [2,6,10] -> even [2,6,10]
    assert pipeline([1,3,5]) == [2,6,10]
def test_pipeline3():
    # [1] -> double [2] -> even [2]
    assert pipeline([1]) == [2]
''',
'''def double(xs):
    return [x*2 for x in xs]
def filter_even(xs):
    return [x for x in xs if x % 2 == 0]
def pipeline(xs):
    return double(filter_even(xs))
''',
"pipeline 描述说先翻倍再过滤,但实现反了(先过滤再翻倍)。注意:此题 desc 故意误导? 不,bug 是顺序反。修正:按 desc 先 double 再 filter -- 实际 test 期望先 double 再 filter even。原代码就是先 double 再 filter,应通过? 重新设计 bug。"),
]

# task18 重新设计:bug 是顺序反(desc 说先过滤再翻倍,实现先翻倍再过滤;或反之)
TASKS[17] = ("18_pipeline_order",
'''def double(xs):
    return [x*2 for x in xs]
def filter_even(xs):
    return [x for x in xs if x % 2 == 0]
def pipeline(xs):
    """先过滤偶数,再翻倍。"""
    return filter_even(double(xs))
''',
'''from source import pipeline
def test_pipeline():
    # [1,2,3,4] -> even [2,4] -> double [4,8]
    assert pipeline([1,2,3,4]) == [4,8]
def test_pipeline2():
    # [2,3] -> even [2] -> double [4]
    assert pipeline([2,3]) == [4]
''',
'''def double(xs):
    return [x*2 for x in xs]
def filter_even(xs):
    return [x for x in xs if x % 2 == 0]
def pipeline(xs):
    return double(filter_even(xs))
''',
"pipeline 描述说先过滤再翻倍,实现却先翻倍再过滤(顺序反)。")

TASKS.append(("19_state_transition",
'''class Door:
    """门状态机:closed->open->closed。不能从 open 再 open。"""
    def __init__(self):
        self.state = "closed"
    def open(self):
        self.state = "open"
    def close(self):
        self.state = "closed"
''',
'''import pytest
from source import Door
def test_open_close():
    d = Door()
    d.open(); assert d.state == "open"
    d.close(); assert d.state == "closed"
def test_double_open_raises():
    d = Door(); d.open()
    with pytest.raises(ValueError):
        d.open()
''',
'''class Door:
    def __init__(self):
        self.state = "closed"
    def open(self):
        if self.state == "open":
            raise ValueError("already open")
        self.state = "open"
    def close(self):
        self.state = "closed"
''',
"Door.open 没校验当前状态,重复 open 不报错。"))

TASKS.append(("20_count_word_boundary",
'''def count_word(text, word):
    """统计 word 作为独立单词出现的次数(不是子串)。"""
    return text.count(word)
''',
'''from source import count_word
def test_simple():
    assert count_word("the cat sat", "cat") == 1
def test_substring_not_counted():
    assert count_word("the cat catalog category", "cat") == 1
def test_multiple():
    assert count_word("cat and cat", "cat") == 2
def test_none():
    assert count_word("dog dog", "cat") == 0
''',
'''def count_word(text, word):
    import re
    return len(re.findall(r"\\b" + re.escape(word) + r"\\b", text))
''',
"count_word 用 str.count,把子串(cat in catalog)也算。应用单词边界。"))


def main():
    os.makedirs(BASE, exist_ok=True)
    for name, src, test, sol, desc in TASKS:
        d = os.path.join(BASE, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "source.py"), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(src))
        with open(os.path.join(d, "test_source.py"), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(test))
        with open(os.path.join(d, "solution.py"), "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(sol))
        with open(os.path.join(d, "task.md"), "w", encoding="utf-8") as f:
            f.write(f"# 任务:{desc}\n")
    print(f"generated {len(TASKS)} tasks to {BASE}")

if __name__ == "__main__":
    main()
