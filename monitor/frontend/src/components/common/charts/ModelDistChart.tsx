// model 分布饼图(by_model {model: {token, runs}})
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { fmtToken } from "@/lib/format";
import { CHART_COLORS } from "@/lib/constants";
import { EmptyState } from "../EmptyState";

const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#71717a"];

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
};

export function ModelDistChart({
  byModel,
  height = 260,
}: {
  byModel: Record<string, { token: number; runs: number }>;
  height?: number;
}) {
  const data = Object.entries(byModel || {})
    .filter(([k]) => k !== "unknown")
    .map(([model, v]) => ({ name: model, token: v.token, runs: v.runs }));
  if (!data.length) return <EmptyState title="暂无 model 分布数据" />;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey="token"
          nameKey="name"
          cx="50%"
          cy="50%"
          outerRadius={80}
          innerRadius={45}
          paddingAngle={2}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(v: number, _n, p: any) => [`${fmtToken(v)} · ${p.payload.runs} runs`, p.payload.name]}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}
