def sum_nested(lst):
    """嵌套列表求和(任意层嵌套)。"""
    total = 0
    for x in lst:
        if isinstance(x, list):
            total += x
        else:
            total += x
    return total
