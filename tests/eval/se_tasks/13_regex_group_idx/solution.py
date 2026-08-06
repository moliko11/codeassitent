import re
def extract_name(s):
    m = re.search(r"(\w+)-(\d+)", s)
    if m:
        return m.group(1)
    return None
