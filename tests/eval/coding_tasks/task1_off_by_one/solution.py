def sum_range(start, end):
    """返回 start 到 end(含两端)的整数和。"""
    total = 0
    for i in range(start, end + 1):
        total += i
    return total
