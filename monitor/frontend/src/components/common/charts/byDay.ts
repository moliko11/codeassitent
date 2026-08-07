// 按天聚合(从 /api/runs 派生,stats.by_day 只有 token 总量,这里拆 input/output/cached + 命中率/成功率)
import type { RunMeta } from "@/lib/types";
import { fmtDate } from "@/lib/format";

export interface DayToken {
  date: string;
  input: number;
  output: number;
  cached: number;
}

export function byDayTokens(runs: RunMeta[]): DayToken[] {
  const m: Record<string, DayToken> = {};
  for (const r of runs) {
    if (!r.started_at || r.started_at <= 0) continue;
    const d = fmtDate(r.started_at);
    const b = m[d] ?? (m[d] = { date: d, input: 0, output: 0, cached: 0 });
    b.input += r.token_input ?? 0;
    b.output += r.token_output ?? 0;
    b.cached += r.token_cached ?? 0;
  }
  return Object.values(m).sort((a, b) => (a.date < b.date ? -1 : 1));
}

export interface DayRate {
  date: string;
  cacheHit: number;
  success: number;
  runs: number;
}

export function byDayRates(runs: RunMeta[]): DayRate[] {
  const m: Record<string, { date: string; cached: number; input: number; rates: number[]; runs: number }> = {};
  for (const r of runs) {
    if (!r.started_at || r.started_at <= 0) continue;
    const d = fmtDate(r.started_at);
    const b = m[d] ?? (m[d] = { date: d, cached: 0, input: 0, rates: [], runs: 0 });
    b.cached += r.token_cached ?? 0;
    b.input += r.token_input ?? 0;
    b.rates.push(r.tool_success_rate ?? 0);
    b.runs += 1;
  }
  return Object.values(m)
    .map((b) => ({
      date: b.date,
      cacheHit: b.input ? b.cached / b.input : 0,
      success: b.rates.length ? b.rates.reduce((s, x) => s + x, 0) / b.rates.length : 0,
      runs: b.runs,
    }))
    .sort((a, b) => (a.date < b.date ? -1 : 1));
}
