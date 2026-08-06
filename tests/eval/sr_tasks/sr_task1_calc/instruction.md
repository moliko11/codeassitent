# 任务:修复 divide 函数的除零处理

calc/ops.py 的 divide(a, b) 在除数为零时静默返回 0,但应该抛 ZeroDivisionError。
请修复 divide,使除零时抛 ZeroDivisionError,其他行为不变。
