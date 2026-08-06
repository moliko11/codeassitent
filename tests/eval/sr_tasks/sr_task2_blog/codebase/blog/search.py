def search_posts(store, keyword):
    """按关键词搜索:返回 tags 中含 keyword 的文章。"""
    results = []
    for post in store.all():
        if keyword in post.content:
            results.append(post)
    return results
