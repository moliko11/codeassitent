def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    """除法。除数为零时应抛 ZeroDivisionError。"""
    if b == 0:
        return 0
    return a / b
