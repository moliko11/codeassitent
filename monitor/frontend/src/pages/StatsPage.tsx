import { useMemo } from "react";
import { useStats, useRuns, useFeedback } from "@/hooks/useQueries";
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
import { StatusBadge } from "@/components/common/StatusBadge";
import { KpiCard } from "@/components/common/KpiCard";
import { RefreshButton } from "@/components/common/RefreshButton";
import { fmtToken, fmtPct } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { Link } from "react-router-dom";
import { Coins, Database, CheckCircle2, Hash, ArrowRight } from "lucide-react";

function ErrorOrEmpty({ q }: { q: { isError: boolean; error: unknown } }) {
  if (q.isError) return <EmptyState title="加载失败" desc={(q.error as ApiError).message} />;
  return null;
}

export function StatsPage() {
  const statsQ = useStats();
  const runsQ = useRuns();
  const fbQ = useFeedback();

  const statusDist = useMemo(() => {
    const m: Record<string, number> = {};
    for (const r of runsQ.data ?? []) m[r.status] = (m[r.status] ?? 0) + 1;
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [runsQ.data]);

  const total = runsQ.data?.length ?? 0;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">统计</h1>
          <p className="text-sm text-[var(--muted-foreground)]">跨 run 维度分析 · 每 15s 自动刷新</p>
        </div>
        <RefreshButton
          onClick={() => {
            statsQ.refetch();
            runsQ.refetch();
          }}
          busy={statsQ.isFetching || runsQ.isFetching}
        />
      </div>

      {statsQ.data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard label="总 token" value={fmtToken(statsQ.data.total_token)} icon={Coins} />
          <KpiCard label="平均命中率" value={fmtPct(statsQ.data.avg_cache_hit_rate)} icon={Database} />
          <KpiCard label="平均成功率" value={fmtPct(statsQ.data.avg_tool_success_rate)} icon={CheckCircle2} />
          <KpiCard label="Run 数" value={statsQ.data.run_count} icon={Hash} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 按 model */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">按 model 分布</CardTitle>
          </CardHeader>
          <CardContent>
            {statsQ.isLoading ? (
              <Skeleton className="h-32" />
            ) : statsQ.data ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>model</TableHead>
                    <TableHead className="text-right">runs</TableHead>
                    <TableHead className="text-right">token</TableHead>
                    <TableHead className="text-right">占比</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(statsQ.data.by_model).map(([m, v]) => (
                    <TableRow key={m}>
                      <TableCell className="text-xs">{m}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{v.runs}</TableCell>
                      <TableCell className="text-right font-mono text-xs">{fmtToken(v.token)}</TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {fmtPct(v.token / (statsQ.data!.total_token || 1))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <ErrorOrEmpty q={statsQ} />
            )}
          </CardContent>
        </Card>

        {/* 按天 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">按天分布</CardTitle>
          </CardHeader>
          <CardContent>
            {statsQ.isLoading ? (
              <Skeleton className="h-32" />
            ) : statsQ.data ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead className="text-right">runs</TableHead>
                    <TableHead className="text-right">token</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(statsQ.data.by_day)
                    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
                    .map(([d, v]) => (
                      <TableRow key={d}>
                        <TableCell className="text-xs">{d}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{v.runs}</TableCell>
                        <TableCell className="text-right font-mono text-xs">{fmtToken(v.token)}</TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            ) : (
              <ErrorOrEmpty q={statsQ} />
            )}
          </CardContent>
        </Card>

        {/* 状态分布 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">状态分布</CardTitle>
          </CardHeader>
          <CardContent>
            {runsQ.isLoading ? (
              <Skeleton className="h-32" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>状态</TableHead>
                    <TableHead className="text-right">数量</TableHead>
                    <TableHead className="text-right">占比</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {statusDist.map(([s, c]) => (
                    <TableRow key={s}>
                      <TableCell>
                        <StatusBadge status={s} />
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">{c}</TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {fmtPct(c / (total || 1))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* 工具分析(Phase 3 §3.5:独立 ToolsPage) */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">工具分析</CardTitle>
          </CardHeader>
          <CardContent>
            <Link
              to="/tools"
              className="inline-flex items-center gap-1.5 text-sm text-[var(--primary)] hover:underline"
            >
              打开工具使用统计页(成功率 / 平均耗时 / 重试 / 超时 / 错误分类)
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* 反馈 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">反馈(👍率)</CardTitle>
        </CardHeader>
        <CardContent>
          {fbQ.isLoading ? (
            <Skeleton className="h-20" />
          ) : fbQ.data && Object.keys(fbQ.data).length ? (
            <pre className="overflow-auto text-xs">{JSON.stringify(fbQ.data, null, 2)}</pre>
          ) : (
            <EmptyState title="无反馈数据" desc="persist/feedback.jsonl 为空" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
