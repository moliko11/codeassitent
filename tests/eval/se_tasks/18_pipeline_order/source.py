def double(xs):
    return [x*2 for x in xs]
def filter_even(xs):
    return [x for x in xs if x % 2 == 0]
def pipeline(xs):
    """先过滤偶数,再翻倍。"""
    return filter_even(double(xs))
