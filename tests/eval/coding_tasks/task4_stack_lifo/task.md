# 任务:修复 Stack 的 bug

`source.py` 的 `Stack` 类应是后进先出(LIFO):最后 push 的元素最先 pop 出来。
但现在 pop 出来的顺序不对。例如 push(1)->push(2)->push(3) 后,pop 应得 3,2,1,实际不是。

请读懂栈的语义,找出 `pop` 方法的错误并修复,使所有测试通过。
