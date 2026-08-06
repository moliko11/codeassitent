from .ops import add, subtract, multiply, divide

def run(op, a, b):
    funcs = {"add": add, "sub": subtract, "mul": multiply, "div": divide}
    return funcs[op](a, b)
