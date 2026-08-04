from source import count_word
def test_simple():
    assert count_word("the cat sat", "cat") == 1
def test_substring_not_counted():
    assert count_word("the cat catalog category", "cat") == 1
def test_multiple():
    assert count_word("cat and cat", "cat") == 2
def test_none():
    assert count_word("dog dog", "cat") == 0
