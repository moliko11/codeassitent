from blog.post import Post
from blog.store import PostStore
from blog.search import search_posts

def test_search_by_tag_not_content():
    s = PostStore()
    s.save(Post("A", "python is great", ["java"]))
    s.save(Post("B", "java is great", ["python"]))
    r = search_posts(s, "python")
    assert len(r) == 1
    assert r[0].title == "B"

def test_search_no_match():
    s = PostStore()
    s.save(Post("A", "python", ["java"]))
    assert search_posts(s, "ruby") == []

def test_search_multiple_tags():
    s = PostStore()
    s.save(Post("A", "x", ["python", "ai"]))
    s.save(Post("B", "y", ["python"]))
    r = search_posts(s, "python")
    assert len(r) == 2
