// token 趋势:按天 input/output/cached 三线(cached 是 input 子集,线图不堆叠避免误导)
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import type { RunMeta } from "@/lib/types";
import { fmtToken } from "@/lib/format";
import { CHART_COLORS } from "@/lib/constants";
import { byDayTokens } from "./byDay";
import { EmptyState } from "../EmptyState";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
};

export function TokenTrendChart({ runs, height = 260 }: { runs: RunMeta[]; height?: number }) {
  const data = byDayTokens(runs);
  if (!data.length) return <EmptyState title="暂无 token 趋势数据" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
        <YAxis
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
          tickFormatter={fmtToken}
          width={48}
        />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => fmtToken(v)} />
        <Legend wrapperStyle={{ fontSize: 12 }} iconType="line" />
        <Line type="monotone" dataKey="input" stroke={CHART_COLORS.input} name="输入" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="output" stroke={CHART_COLORS.output} name="输出" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="cached" stroke={CHART_COLORS.cached} name="缓存命中" strokeWidth={2} dot={false} strokeDasharray="4 3" />
      </LineChart>
    </ResponsiveContainer>
  );
}
