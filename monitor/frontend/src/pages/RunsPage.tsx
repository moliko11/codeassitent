import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRuns } from "@/hooks/useQueries";
import { RunsTable, type SortKey, type SortDir } from "@/components/runs/RunsTable";
import { RunsTableToolbar } from "@/components/runs/RunsTableToolbar";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/EmptyState";
import { ApiError } from "@/lib/api";

export function RunsPage() {
  const q = useRuns();
  const nav = useNavigate();
  const [sortKey, setSortKey] = useState<SortKey>("started_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [modelFilter, setModelFilter] = useState<Set<string>>(new Set());

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("desc");
    }
  };

  const filtered = useMemo(() => {
    let arr = q.data ?? [];
    if (statusFilter.size) arr = arr.filter((r) => statusFilter.has(r.status));
    if (modelFilter.size) arr = arr.filter((r) => modelFilter.has(r.model));
    const dir = sortDir === "asc" ? 1 : -1;
    return [...arr].sort((a, b) => {
      const av = (a[sortKey] ?? 0) as number;
      const bv = (b[sortKey] ?? 0) as number;
      return (av - bv) * dir;
    });
  }, [q.data, statusFilter, modelFilter, sortKey, sortDir]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Runs</h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          {q.data?.length ?? 0} 个会话{filtered.length !== q.data?.length ? ` · 筛选后 ${filtered.length}` : ""}
        </p>
      </div>

      {q.isLoading ? (
        <Skeleton className="h-96" />
      ) : q.isError ? (
        <EmptyState title="加载失败" desc={(q.error as ApiError).message} />
      ) : q.data && q.data.length ? (
        <>
          <RunsTableToolbar
            runs={q.data}
            statusFilter={statusFilter}
            onStatusFilter={setStatusFilter}
            modelFilter={modelFilter}
            onModelFilter={setModelFilter}
          />
          <Card>
            <CardContent className="p-2">
              <RunsTable
                runs={filtered}
                sortKey={sortKey}
                sortDir={sortDir}
                onSort={onSort}
                onRowClick={(id) => nav(`/runs/${id}`)}
              />
            </CardContent>
          </Card>
        </>
      ) : (
        <EmptyState title="无会话" desc="先跑一个:python -m agent.agentloop(exit 退出)" />
      )}
    </div>
  );
}
