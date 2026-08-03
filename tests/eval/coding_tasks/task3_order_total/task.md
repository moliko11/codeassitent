# 任务:修复订单总价计算的 bug

`source.py` 实现了订单总价计算:小计 -> 折扣 -> 加税。`calculate_total` 的注释说"税基于折扣后金额",
但含折扣的订单总价算出来不对。例如 `calculate_total([{price:10,qty:2}], discount=5)` 期望 16.5,
实际不是。

请读懂三个函数的调用关系,找出 `calculate_total` 里的逻辑错误并修复,使所有测试通过。
