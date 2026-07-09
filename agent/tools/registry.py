# 工具注册表与执行器
# 可靠性(retry/熔断/幂等/审计)在 execute 内部；流式(as_completed+sink)在 _parallel 层。
# 两者正交：_parallel 并行调度 + 发 ToolStart/ToolEnd，execute 内部走可靠性管道。
import time

import jsonschema
from jsonschema.exceptions import ValidationError

from ..core.errors import ToolTimeoutError, classify_tool_error
from ..reliability.retry import RetryPolicy
from ..reliability.idempotency import IdempotencyStore
from ..reliability.audit import AuditLogger
from ..reliability.breaker import BreakerConfig, CircuitBreaker

from .formatter import ToolResultFormatter

from .defs import Tool, ToolCall, ToolResult, ToolSpec
from ..streaming.events import ToolStart, ToolEnd


def _result_summary(result: ToolResult) -> str | None:
    """ToolEnd 摘要：成功取格式化后的 text（截断），失败取 error.message。"""
    if result.ok:
        t = result.text
        if not t:
            return None
        return t if len(t) <= 80 else t[:80] + "…"
    return (result.error or {}).get("message")


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        name = tool.tool_spec.name
        if name in self.tools:
            raise ValueError(f"Tool with name '{name}' is already registered.")
        self.tools[name] = tool

    def get_tool(self, name: str) -> Tool:
        if name not in self.tools:
            raise ValueError(f"Tool with name '{name}' is not registered.")
        return self.tools[name]

    def list_tools(self) -> list[Tool]:
        return list(self.tools.values())


# 模块级默认注册表实例：@tool 装饰器向它注册
registry = ToolRegistry()


def tool(name, description, input_schema, examples=None, returns="",
         idempotent=False, fallback_tool_name=None):
    def decorator(func):
        registry.register(Tool(
            tool_spec=ToolSpec(name=name, description=description,
                               input_schema=input_schema,
                               examples=examples or [], returns=returns,
                               idempotent=idempotent, fallback_tool_name=fallback_tool_name),
            handler=func,
        ))
        return func
    return decorator


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, formatter=None, *,
                 retry_policy: RetryPolicy = None, retry_mode="llm_retry",
                 breaker_config=BreakerConfig(), idempotency_store: IdempotencyStore = None,
                 audit_logger: AuditLogger = None):
        """工具执行器。

        可靠性参数（均可选，不传则该机制不生效）：
        - retry_policy: RetryPolicy，失败重试策略（指数退避+jitter）。
        - retry_mode: "runtime_retry"（Runtime 自动重试）/ "llm_retry"（只跑一次，失败回填模型）。
        - breaker_config: 熔断器配置，per-tool 保护下游。
        - idempotency_store: 幂等去重缓存，按 key 缓存成功结果。
        - audit_logger: 审计日志，记录 who/what/when/result。
        """
        self.registry = registry
        self.formatter = formatter or ToolResultFormatter()
        self.retry_policy = retry_policy
        self.retry_mode = retry_mode
        self.breaker_config = breaker_config
        self.idempotency_store = idempotency_store
        self.audit_logger = audit_logger
        self._breakers: dict[str, CircuitBreaker] = {}   # per-tool 懒建

    def _get_breaker(self, tool_name) -> CircuitBreaker:
        return self._breakers.setdefault(tool_name, CircuitBreaker(self.breaker_config))

    def execute(self, call, *, timeout=None, cancel_event=None, user_id=None) -> ToolResult:
        """工具执行管道：审计 -> 前置门禁 -> 幂等 -> 熔断 -> retry -> 熔断记录 -> 幂等缓存 -> fallback -> 收尾。

        流式（ToolStart/ToolEnd）不在本方法发——由 _parallel 层负责，保持 execute 纯净。
        """
        start_ts = self._audit_before(call, user_id)

        # 0. 前置门禁(工具存在 + schema)
        tool, pre_err = self._precheck(call)
        if pre_err is not None:
            return self._done(pre_err, call, user_id, start_ts)

        # 1. 幂等命中 -> 直接返回缓存
        if tool.tool_spec.idempotent and self.idempotency_store is not None:
            cached = self.idempotency_store.get(call)
            if cached is not None:
                hit = ToolResult(call_id=call.call_id, tool_name=call.tool_name,
                                 ok=True, data=cached, meta={**call.meta, "cache_hit": True})
                return self._done(hit, call, user_id, start_ts)

        # 2. 熔断闸门
        breaker = self._get_breaker(call.tool_name)
        if not breaker.allow_request():
            blocked = ToolResult(call_id=call.call_id, tool_name=call.tool_name, ok=False,
                error={"type": "CircuitOpen", "message": "熔断中,工具暂不可用", "retryable": False},
                meta=call.meta)
            return self._done(blocked, call, user_id, start_ts)

        # 3. retry 循环(含超时)
        result = self._execute_with_retry(tool, call, timeout, cancel_event)

        if (result.error or {}).get("type") == "Cancelled":
            return self._done(result, call, user_id, start_ts)   # 取消:短路,不记熔断、不 fallback

        # 4. 熔断记录(call 级,不是 attempt 级)
        if result.ok:
            breaker.record_success()
        else:
            breaker.record_failure()

        # 5. 幂等缓存(只存成功)
        if result.ok and tool.tool_spec.idempotent and self.idempotency_store is not None:
            self.idempotency_store.set(call, result.data)

        # 6. fallback
        if not result.ok and tool.tool_spec.fallback_tool_name:
            result = self._run_fallback(call, tool.tool_spec.fallback_tool_name, timeout, cancel_event)

        # 7. 收尾
        return self._done(result, call, user_id, start_ts)

    def _precheck(self, call):
        """前置门禁：工具存在 + schema。返回 (tool, error)。
        error 为 None=通过；非 None=不可重试的失败 ToolResult（未 finalize）。"""
        try:
            tool = self.registry.get_tool(call.tool_name)
        except Exception as e:
            return None, ToolResult(
                call_id=call.call_id, tool_name=call.tool_name, ok=False,
                error={"type": "ToolNotFound", "message": str(e), "retryable": False},
                meta=call.meta,
            )
        try:
            jsonschema.validate(instance=call.arguments, schema=tool.tool_spec.input_schema)
        except jsonschema.ValidationError as e:
            return None, ToolResult(
                call_id=call.call_id, tool_name=call.tool_name, ok=False,
                error={"type": "SchemaValidationError", "message": e.message,
                       "field": list(e.absolute_path), "retryable": False},
                meta=call.meta,
            )
        return tool, None

    def _finalize(self, result: ToolResult) -> ToolResult:
        """统一设 text（结构化 + 压缩），由 formatter 完成。"""
        result.text = self.formatter.format(result)
        return result

    def execute_many(self, calls, timeout=None, *, cancel_event=None, user_id=None, sink=None):
        """并行执行多个 tool_calls。有 depends_on 时按 DAG 层级并发。

        sink：可选 EventSink；传入则在每个工具开始/完成时发 ToolStart/ToolEnd。
        cancel_event/user_id：透传给 execute（可靠性管道用）。
        """
        if not any(c.depends_on for c in calls):
            return self._parallel(calls, timeout, cancel_event=cancel_event, user_id=user_id, sink=sink)
        return self._dag_execute(calls, timeout, cancel_event=cancel_event, user_id=user_id, sink=sink)

    def _run_with_timeout(self, handler, args, timeout, cancel_event):
        """单工具超时包装。timeout=None 不限时。超时抛 ToolTimeoutError（可重试）。"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        if timeout is None:
            return handler(**args)
        # ⚠️ 不用 with：with 退出会 shutdown(wait=True) 等孤儿线程，超时就废了
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(handler, **args)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            raise ToolTimeoutError(f"工具执行超时（{timeout}s）")
        finally:
            pool.shutdown(wait=False)   # 不等孤儿线程(它继续跑到结束)

    def _execute_with_retry(self, tool, call, timeout, cancel_event):
        """单工具 retry 循环。llm_retry/无 policy 只跑一次；runtime_retry 按 policy 重试。"""
        policy = self.retry_policy

        def mk(ok, **kw):
            return ToolResult(call_id=call.call_id, tool_name=call.tool_name,
                              meta=call.meta, ok=ok, **kw)

        # llm_retry 或无 policy：只跑一次，失败交回 agentloop 回填模型
        if self.retry_mode != "runtime_retry" or policy is None:
            try:
                return mk(True, data=self._run_with_timeout(tool.handler, call.arguments, timeout, cancel_event))
            except Exception as e:
                return mk(False, error=classify_tool_error(e))

        # runtime_retry：重试循环
        last_err = None
        for attempt in range(policy.max_attempts):
            if cancel_event and cancel_event.is_set():
                return mk(False, error={"type": "Cancelled", "message": "执行被取消", "retryable": False})
            try:
                return mk(True, data=self._run_with_timeout(tool.handler, call.arguments, timeout, cancel_event))
            except Exception as e:
                last_err = classify_tool_error(e)
                if not policy.should_retry(last_err) or attempt == policy.max_attempts - 1:
                    break                       # 不可重试 / 用尽次数
                if cancel_event and cancel_event.wait(policy.backoff(attempt)):
                    return mk(False, error={"type": "Cancelled", "message": "执行被取消", "retryable": False})
        return mk(False, error=last_err)

    def _audit_before(self, call, user_id):
        """记开始时间；没配 audit_logger 返回 None。"""
        return self.audit_logger.log_before(call, user_id) if self.audit_logger else None

    def _done(self, result, call, user_id, start_ts):
        """统一收尾：记审计 + 设 text(finalize)。所有 return 点走这里。"""
        if self.audit_logger:
            self.audit_logger.log_after(call, user_id, start_ts,
                ok=result.ok,
                error_type=(result.error or {}).get("type") if not result.ok else None)
        return self._finalize(result)

    def _run_fallback(self, call, fallback_name, timeout, cancel_event):
        """主工具失败后调备用工具（单次，不 retry）。参数沿用主调用。"""
        try:
            fb_tool = self.registry.get_tool(fallback_name)
        except Exception as e:
            return ToolResult(call_id=call.call_id, tool_name=fallback_name, ok=False,
                error={"type": "FallbackNotFound", "message": str(e), "retryable": False},
                meta={**call.meta, "via_fallback": True})
        try:
            data = self._run_with_timeout(fb_tool.handler, call.arguments, timeout, cancel_event)
            return ToolResult(call_id=call.call_id, tool_name=fallback_name, ok=True,
                              data=data, meta={**call.meta, "via_fallback": True})
        except Exception as e:
            return ToolResult(call_id=call.call_id, tool_name=fallback_name, ok=False,
                              error=classify_tool_error(e),
                              meta={**call.meta, "via_fallback": True})

    def _parallel(self, calls, timeout=None, *, cancel_event=None, user_id=None, sink=None):
        """并行执行一组无依赖的 tool_calls。

        streaming 层：as_completed（谁完成谁出）+ sink.emit(ToolStart/ToolEnd)。
        可靠性：透传 cancel_event/user_id 给 execute（execute 内部走 retry/熔断/幂等/审计）。
        ToolStart/ToolEnd 在本层发（而非 execute 内），这样超时杀死 future 时
        不会与 execute 内部的事件重复（execute 保持纯净、不发事件）。
        """
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
        if not calls:
            return []
        if sink:
            for c in calls:
                sink.emit(ToolStart(
                    call_id=c.call_id, tool_name=c.tool_name, arguments=c.arguments))
        results_by_call_id: dict[str, ToolResult] = {}
        with ThreadPoolExecutor(max_workers=min(len(calls), 8)) as pool:
            fut_map = {pool.submit(self.execute, c, timeout=timeout,
                                   cancel_event=cancel_event, user_id=user_id): c for c in calls}
            for fut in as_completed(fut_map):
                c = fut_map[fut]
                try:
                    r = fut.result(timeout=timeout)
                    results_by_call_id[c.call_id] = r
                    if sink:
                        sink.emit(ToolEnd(
                            call_id=r.call_id, tool_name=r.tool_name, ok=r.ok,
                            error_type=(r.error or {}).get("type") if r.error else None,
                            summary=_result_summary(r)))
                except FuturesTimeout:
                    r = self._finalize(ToolResult(
                        call_id=c.call_id, tool_name=c.tool_name, ok=False,
                        error={"type": "StepTimeout", "message": f"工具执行超时（{timeout}s）", "retryable": True},
                        meta=c.meta,
                    ))
                    results_by_call_id[c.call_id] = r
                    if sink:
                        sink.emit(ToolEnd(
                            call_id=r.call_id, tool_name=r.tool_name, ok=False,
                            error_type="StepTimeout", summary=r.error["message"]))
        # 保持与输入 calls 相同的顺序返回
        return [results_by_call_id[c.call_id] for c in calls]

    def _dag_execute(self, calls: list[ToolCall], timeout=None, *, cancel_event=None, user_id=None, sink=None) -> list[ToolResult]:
        """按 DAG 层级执行 tool_calls，支持 depends_on。每层并行，层级间串行。"""
        # 1. 构建 call_id -> ToolCall 映射
        by_id = {c.call_id: c for c in calls}
        done_ids: set[str] = set()
        results: list[ToolResult] = []
        remaining = list(calls)
        while remaining:
            # 本层：依赖都已完成的
            layer = [c for c in remaining if all(d in done_ids for d in c.depends_on)]
            if not layer:
                # 有环：剩余的强制执行（防死锁）
                layer = remaining
            layer_results = self._parallel(layer, timeout,
                                           cancel_event=cancel_event, user_id=user_id, sink=sink)
            results.extend(layer_results)
            done_ids.update(c.call_id for c in layer)
            remaining = [c for c in remaining if c.call_id not in done_ids]
        return results
