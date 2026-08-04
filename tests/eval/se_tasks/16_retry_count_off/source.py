def retry(fn, times):
    """重试 fn 最多 times 次,全失败返回最后一次异常。"""
    last = None
    for i in range(times - 1):
        try:
            return fn()
        except Exception as e:
            last = e
    raise last
