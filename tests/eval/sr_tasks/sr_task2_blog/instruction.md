# 任务:修复 search_posts 的匹配字段

blog/search.py 的 search_posts(store, keyword) 本应返回 tags 中含 keyword 的文章,
但现在匹配的是 content 字段,导致搜 tag 'python' 会误返回 content 含 python 的文章。
请修复:只匹配 post.tags,不匹配 content。
