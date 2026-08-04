def max_val(nums):
    m = float("-inf")
    for n in nums:
        if n > m:
            m = n
    return m
