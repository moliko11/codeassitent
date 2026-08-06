def get_col(row, idx):
    """取 CSV 行第 idx 列(0-based)。"""
    return row.split(",")[idx + 1]
