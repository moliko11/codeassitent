def reverse_words(sentence):
    """反转句子中每个单词的字母,单词顺序不变,返回新字符串。"""
    words = sentence.split()
    reversed_words = [w[::-1] for w in words]
    return " ".join(reversed_words)
