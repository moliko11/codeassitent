import re
def extract_name(s):
    """从 'name-123' 格式提取 name 部分。"""
    m = re.search(r"(\w+)-(\d+)", s)
    if m:
        return m.group(2)
    return None
