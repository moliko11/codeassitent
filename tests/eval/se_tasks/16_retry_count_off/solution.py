def retry(fn, times):
    last = None
    for i in range(times):
        try:
            return fn()
        except Exception as e:
            last = e
    raise last
