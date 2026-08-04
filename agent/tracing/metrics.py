# tracing/metrics.py - MetricsCollector + RunReport(阶段9 任务3,题6/7/8/18/19)
# 从 trace spans 聚合,不新埋点(字段已有:usage/tool ok/duration/status)。
# retry_count 依赖 commit 3 补的 tool span attrs["attempts"]。
from dataclasses import dataclass


@dataclass
class RunReport:
    """一次 run 的指标汇总。"""
    run_id: str
    status: str = "unknown"
    duration_ms: float = 0.0
    step_count: int = 0
    tool_count: int = 0
    tool_success_count: int = 0
    tool_success_rate: float = 0.0
    avg_tool_latency_ms: float = 0.0
    token_input: int = 0
    token_output: int = 0
    token_total: int = 0
    token_cached: int = 0           # 缓存命中 token(cached_tokens 之和,是 input 子集;命中率=cached/input)
    timeout_count: int = 0
    retry_count: int = 0

    def to_dict(self) -> dict:
        return {**self.__dict__}


class MetricsCollector:
    """从 trace 聚合 RunReport。字段大多已有,只补 retry_count(依赖 commit 3 的 attempts)。"""

    def collect(self, trace) -> RunReport:
        rep = RunReport(run_id=trace.run_id)
        tool_durations = []
        for span in trace.spans:
            if span.type == "run":
                rep.status = span.attrs.get("status", "unknown")
                rep.duration_ms = span.duration_ms() or 0.0
            elif span.type == "step":
                rep.step_count += 1
                u = span.attrs.get("usage")
                if u:
                    rep.token_input += u.get("input_tokens", 0)
                    rep.token_output += u.get("output_tokens", 0)
                    rep.token_total += u.get("total_tokens", 0)
                    rep.token_cached += u.get("cached_tokens", 0) or 0
            elif span.type == "tool":
                rep.tool_count += 1
                if span.attrs.get("ok"):
                    rep.tool_success_count += 1
                d = span.duration_ms()
                if d is not None:
                    tool_durations.append(d)
                et = span.attrs.get("error_type")
                if et and "Timeout" in str(et):
                    rep.timeout_count += 1
                # retry:attempts > 1 才算重试(attempts=1 是首次成功,无重试)
                attempts = span.attrs.get("attempts", 1)
                if attempts > 1:
                    rep.retry_count += attempts - 1
        rep.tool_success_rate = (rep.tool_success_count / rep.tool_count) if rep.tool_count else 0.0
        rep.avg_tool_latency_ms = (sum(tool_durations) / len(tool_durations)) if tool_durations else 0.0
        return rep
