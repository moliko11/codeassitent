def merge(a, b):
    """深合并两个配置 dict(嵌套 dict 递归合并,非 dict 覆盖)。"""
    return {**a, **b}
