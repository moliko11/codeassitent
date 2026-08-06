from source import reverse_words

def test_basic():
    assert reverse_words("hello world") == "olleh dlrow"

def test_single_word():
    assert reverse_words("python") == "nohtyp"

def test_multiple():
    assert reverse_words("a b c") == "a b c"
