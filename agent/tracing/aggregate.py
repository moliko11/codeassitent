# tracing/aggregate.py - 跨 run 聚合(监控 M1,对齐 monitor-dashboard-plan §3.4)
# 输入 = list_runs() 的 run_meta 摘要列表(每项一个 run 的 meta),聚合 token/成功率/按天/按 model。
# by_tool 需逐 run load trace(慢),列表聚合不做(详情页/M2 才做)。
# cost = TODO(§8),本期恒 0。
#
# 关键坑(见 plan §7):
# - 坑1:token 用 run_meta 里的(源自 step span attrs["usage"],LLM 返回的精确值),不是估算。
# - 坑4:个别 provider total_tokens=0/缺失,聚合用 input+output 兜底(_total_with_fallback)。
# - by_day 需要墙钟日期:run_meta.started_at 是墙钟(agentloop 写侧车时 time.time() 回推),
#   退化 run(无侧车)started_at=0 -> 桶 'unknown'。
import time
from dataclasses import dataclass, field


@dataclass
class AggregateStats:
    """跨 run 聚合指标。"""
    run_count: int = 0
    total_token_input: int = 0
    total_token_output: int = 0
    total_token: int = 0
    avg_tool_success_rate: float = 0.0
    total_cost: float = 0.0          # TODO(§8),本期恒 0
    by_day: dict = field(default_factory=dict)    # {date: {token, runs}}
    by_model: dict = field(default_factory=dict)  # {model: {token, runs}}

    def to_dict(self) -> dict:
        return {**self.__dict__}


def _day_of(ts) -> str:
    """墙钟 timestamp -> 'YYYY-MM-DD'(本地时区)。ts<=0(退化 run 无墙钟)-> 'unknown'。"""
    if not ts or ts <= 0:
        return "unknown"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _total_with_fallback(r: dict) -> int:
    """坑4:total 缺失/0 时用 input+output 兜底,别直接信 total。"""
    t = r.get("token_total", 0) or 0
    if t > 0:
        return t
    return (r.get("token_input", 0) or 0) + (r.get("token_output", 0) or 0)


def aggregate_stats(runs: list[dict]) -> AggregateStats:
    """runs = list_runs() 结果(每项是 run_meta)。聚合 token/成功率/按天/按 model。
    by_tool 需逐 run load trace(慢),列表聚合跳过(详情页才做)。"""
    s = AggregateStats()
    rates = []
    for r in runs:
        s.run_count += 1
        s.total_token_input += r.get("token_input", 0) or 0
        s.total_token_output += r.get("token_output", 0) or 0
        s.total_token += _total_with_fallback(r)
        rates.append(r.get("tool_success_rate", 0) or 0)
        day = _day_of(r.get("started_at"))
        d = s.by_day.setdefault(day, {"token": 0, "runs": 0})
        d["token"] += _total_with_fallback(r)
        d["runs"] += 1
        m = s.by_model.setdefault(r.get("model") or "unknown", {"token": 0, "runs": 0})
        m["token"] += _total_with_fallback(r)
        m["runs"] += 1
    s.avg_tool_success_rate = (sum(rates) / len(rates)) if rates else 0.0
    return s
