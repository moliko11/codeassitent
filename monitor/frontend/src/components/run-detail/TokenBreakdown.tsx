// 每步 token 明细(从 trace step span usage)。堆叠:缓存命中 + 新输入(input-cached) + 输出,
// 总和 = input + output(cached 是 input 子集,不重复计)。
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Trace } from "@/lib/types";
import { fmtToken } from "@/lib/format";
import { CHART_COLORS } from "@/lib/constants";
import { EmptyState } from "@/components/common/EmptyState";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
};

export function TokenBreakdown({ trace }: { trace: Trace | null | undefined }) {
  const steps = (trace?.spans ?? [])
    .filter((s) => s.type === "step" && s.attrs?.usage)
    .map((s, i) => {
      const u = s.attrs!.usage!;
      const cached = u.cached_tokens ?? 0;
      return {
        step: `#${s.name ?? i}`,
        cached,
        fresh: Math.max(u.input_tokens - cached, 0),
        output: u.output_tokens,
      };
    });

  if (!steps.length)
    return <EmptyState title="无 token 明细" desc="trace 无 step span usage(可能 trace 不存在)" />;

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={steps} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
        <XAxis dataKey="step" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
        <YAxis
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
          tickFormatter={fmtToken}
          width={48}
        />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => fmtToken(v)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="cached" stackId="t" fill={CHART_COLORS.cached} name="缓存命中" />
        <Bar dataKey="fresh" stackId="t" fill={CHART_COLORS.input} name="输入(新)" />
        <Bar dataKey="output" stackId="t" fill={CHART_COLORS.output} name="输出" />
      </BarChart>
    </ResponsiveContainer>
  );
}
