// 工具使用统计页(Phase 3 §3.5):/api/stats/tools 逐 run load trace 聚合。
// 表格 + 调用分布饼图(Recharts,同 ModelDistChart 风格)+ 成功率条。
import { useMemo } from "react";
import { useTools } from "@/hooks/useQueries";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { RefreshButton } from "@/components/common/RefreshButton";
import { KpiCard } from "@/components/common/KpiCard";
import { Wrench, CheckCircle2, RefreshCcw, TimerOff } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";
import { fmtDur, fmtPct } from "@/lib/format";
import { ApiError } from "@/lib/api";

const PALETTE = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#71717a"];

const tooltipStyle = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
};

export function ToolsPage() {
  const q = useTools();
  const tools = q.data ?? [];

  const agg = useMemo(() => {
    let calls = 0,
      ok = 0,
      retries = 0,
      timeouts = 0;
    for (const t of tools) {
      calls += t.call_count;
      ok += t.success_count;
      retries += t.retry_count;
      timeouts += t.timeout_count;
    }
    return { calls, ok, retries, timeouts };
  }, [tools]);

  const pieData = tools.map((t) => ({ name: t.tool, value: t.call_count }));

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">工具使用统计</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            逐 run load trace 聚合 tool span · 每 15s 自动刷新
          </p>
        </div>
        <RefreshButton onClick={() => q.refetch()} busy={q.isFetching} />
      </div>

      {q.isLoading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : q.isError ? (
        <EmptyState title="加载失败" desc={(q.error as ApiError).message} />
      ) : !tools.length ? (
        <EmptyState title="无工具调用" desc="尚无 run 生成 trace(跑一次 agentloop 后回来)" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <KpiCard label="总调用" value={agg.calls} icon={Wrench} />
            <KpiCard label="总成功率" value={fmtPct(agg.ok / (agg.calls || 1))} icon={CheckCircle2} />
            <KpiCard label="重试" value={agg.retries} icon={RefreshCcw} />
            <KpiCard label="超时" value={agg.timeouts} icon={TimerOff} />
          </div>

          <div className="grid gap-4 lg:grid-cols-5">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">调用分布</CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      innerRadius={45}
                      paddingAngle={2}
                    >
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(v: number, _n, p: any) => [
                        `${v} 次 (${fmtPct(v / (agg.calls || 1))})`,
                        p.payload.name,
                      ]}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="lg:col-span-3">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">明细({tools.length} 个工具)</CardTitle>
              </CardHeader>
              <CardContent className="p-2">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>工具</TableHead>
                      <TableHead className="text-right">调用</TableHead>
                      <TableHead className="text-right">成功率</TableHead>
                      <TableHead className="text-right">平均耗时</TableHead>
                      <TableHead className="text-right">重试</TableHead>
                      <TableHead className="text-right">超时</TableHead>
                      <TableHead>错误类型</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tools.map((t) => (
                      <TableRow key={t.tool}>
                        <TableCell className="font-mono text-xs">{t.tool}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{t.call_count}</TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          <span
                            className={
                              t.success_rate >= 1
                                ? "text-emerald-600 dark:text-emerald-400"
                                : t.success_rate < 0.8
                                  ? "text-rose-600 dark:text-rose-400"
                                  : ""
                            }
                          >
                            {fmtPct(t.success_rate)} ({t.success_count}/{t.call_count})
                          </span>
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {fmtDur(t.avg_elapsed_ms)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {t.retry_count > 0 ? t.retry_count : "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {t.timeout_count > 0 ? t.timeout_count : "-"}
                        </TableCell>
                        <TableCell className="text-[11px]">
                          {Object.keys(t.error_types).length
                            ? Object.entries(t.error_types)
                                .map(([k, n]) => `${k}×${n}`)
                                .join(", ")
                            : "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
