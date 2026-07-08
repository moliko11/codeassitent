from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from ..core.errors import StepTimeout

_executor = ThreadPoolExecutor(max_workers=4)
    
def call_with_timeout(fn, *args, timeout: float, **kwargs):
    """用线程池包装同步调用，超时抛 StepTimeout。
    局限：超时后底层线程仍在跑（学习项目可接受；生产建议用 SDK 原生 timeout）。"""
    future = _executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        raise StepTimeout(f"{getattr(fn, '__name__', fn)} 超时 ({timeout}s)")
