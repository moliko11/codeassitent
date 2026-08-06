def count_word(text, word):
    import re
    return len(re.findall(r"\b" + re.escape(word) + r"\b", text))
