// 命中率 + 成功率趋势(按天,0-1 -> 百分比)
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import type { RunMeta } from "@/lib/types";
import { fmtPct } from "@/lib/format";
import { CHART_COLORS } from "@/lib/constants";
import { byDayRates } from "./byDay";
import { EmptyState } from "../EmptyState";

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
};

export function RateTrendChart({ runs, height = 220 }: { runs: RunMeta[]; height?: number }) {
  const data = byDayRates(runs);
  if (!data.length) return <EmptyState title="暂无趋势数据" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} vertical={false} />
        <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="var(--muted-foreground)" />
        <YAxis
          tick={{ fontSize: 11 }}
          stroke="var(--muted-foreground)"
          tickFormatter={(v: number) => Math.round(v * 100) + "%"}
          domain={[0, 1]}
          width={40}
        />
        <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => fmtPct(v)} />
        <Legend wrapperStyle={{ fontSize: 12 }} iconType="line" />
        <Line type="monotone" dataKey="cacheHit" stroke={CHART_COLORS.cached} name="缓存命中率" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="success" stroke={CHART_COLORS.ok} name="工具成功率" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
