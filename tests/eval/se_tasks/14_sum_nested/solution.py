def sum_nested(lst):
    total = 0
    for x in lst:
        if isinstance(x, list):
            total += sum_nested(x)
        else:
            total += x
    return total
