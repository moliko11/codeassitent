import { Link } from "react-router-dom";
import { Coins, ArrowDownToLine, ArrowUpFromLine, Database, Hash, CheckCircle2 } from "lucide-react";
import { useStats, useRuns } from "@/hooks/useQueries";
import { KpiCard } from "@/components/common/KpiCard";
import { RefreshButton } from "@/components/common/RefreshButton";
import { TokenTrendChart } from "@/components/common/charts/TokenTrendChart";
import { ModelDistChart } from "@/components/common/charts/ModelDistChart";
import { RateTrendChart } from "@/components/common/charts/RateTrendChart";
import { RecentRunsTable } from "@/components/runs/RecentRunsTable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { fmtToken, fmtPct } from "@/lib/format";
import { ApiError } from "@/lib/api";

function ErrorState({ message }: { message: string }) {
  return <EmptyState title="加载失败" desc={message} />;
}

export function DashboardPage() {
  const statsQ = useStats();
  const runsQ = useRuns();

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            跨会话聚合 · token / 缓存 / 工具成功率(每 15s 自动刷新)
          </p>
        </div>
        <RefreshButton
          onClick={() => {
            statsQ.refetch();
            runsQ.refetch();
          }}
          busy={statsQ.isFetching || runsQ.isFetching}
        />
      </div>

      {/* KPI 卡片 */}
      {statsQ.isLoading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : statsQ.isError ? (
        <ErrorState message={(statsQ.error as ApiError).message} />
      ) : statsQ.data ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <KpiCard label="总 token" value={fmtToken(statsQ.data.total_token)} icon={Coins} />
          <KpiCard
            label="输入"
            value={fmtToken(statsQ.data.total_token_input)}
            sub={`${statsQ.data.run_count} runs`}
            icon={ArrowDownToLine}
          />
          <KpiCard
            label="输出"
            value={fmtToken(statsQ.data.total_token_output)}
            icon={ArrowUpFromLine}
          />
          <KpiCard
            label="缓存命中"
            value={fmtToken(statsQ.data.total_token_cached)}
            sub={`命中率 ${fmtPct(statsQ.data.avg_cache_hit_rate)}`}
            icon={Database}
          />
          <KpiCard label="Run 数" value={statsQ.data.run_count} icon={Hash} />
          <KpiCard
            label="平均成功率"
            value={fmtPct(statsQ.data.avg_tool_success_rate)}
            icon={CheckCircle2}
          />
          <KpiCard label="cost" value="-" sub="待 pricing 表" icon={Coins} />
        </div>
      ) : null}

      {/* 趋势图 */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Token 用量趋势(按天)</CardTitle>
          </CardHeader>
          <CardContent>
            {runsQ.isLoading ? (
              <Skeleton className="h-[260px]" />
            ) : runsQ.isError ? (
              <ErrorState message={(runsQ.error as ApiError).message} />
            ) : runsQ.data ? (
              <TokenTrendChart runs={runsQ.data} />
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Model 分布</CardTitle>
          </CardHeader>
          <CardContent>
            {statsQ.isLoading ? (
              <Skeleton className="h-[260px]" />
            ) : statsQ.data ? (
              <ModelDistChart byModel={statsQ.data.by_model} />
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">命中率 / 成功率趋势</CardTitle>
        </CardHeader>
        <CardContent>
          {runsQ.isLoading ? (
            <Skeleton className="h-[220px]" />
          ) : runsQ.data ? (
            <RateTrendChart runs={runsQ.data} />
          ) : null}
        </CardContent>
      </Card>

      {/* 近期会话 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm">近期会话</CardTitle>
          <Link to="/runs" className="text-xs text-[var(--primary)] hover:underline">
            全部 →
          </Link>
        </CardHeader>
        <CardContent>
          {runsQ.isLoading ? (
            <Skeleton className="h-40" />
          ) : runsQ.isError ? (
            <ErrorState message={(runsQ.error as ApiError).message} />
          ) : runsQ.data ? (
            <RecentRunsTable runs={runsQ.data.slice(0, 10)} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
