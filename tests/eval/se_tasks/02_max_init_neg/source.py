def max_val(nums):
    """返回最大值。"""
    m = 0
    for n in nums:
        if n > m:
            m = n
    return m
