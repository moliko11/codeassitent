# 任务:修复 LRUCache 的 bug

`source.py` 的 `LRUCache` 应在容量满时淘汰"最久未使用"的 key。`get`/`put` 都应把访问的 key
标记为最近使用(移到 order 末尾)。但当用 `put` 更新一个已存在 key 的值时,淘汰行为不对--
可能淘汰了刚更新的 key。例如 put(1,1)->put(2,2)->put(1,100)->put(3,3) 后,1 应还在(值 100),
2 应被淘汰,但实际不是。

请读懂 LRU 的 recency 机制,找出 `put` 方法里更新已存在 key 时的遗漏并修复,使所有测试通过。
