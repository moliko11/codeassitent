import type * as React from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusBadge } from "@/components/common/StatusBadge";
import { EmptyState } from "@/components/common/EmptyState";
import { fmtTs, fmtDur, fmtToken, fmtPct, shortId, cacheHitRate } from "@/lib/format";
import type { RunMeta } from "@/lib/types";
import { cn } from "@/lib/cn";
import { ArrowUp, ArrowDown, ChevronsUpDown } from "lucide-react";

export type SortKey =
  | "started_at"
  | "duration_ms"
  | "token_total"
  | "token_input"
  | "token_output"
  | "token_cached"
  | "step_count"
  | "tool_count"
  | "tool_success_rate";
export type SortDir = "asc" | "desc";

interface Col {
  key: SortKey;
  label: string;
  align?: "right";
  render: (r: RunMeta) => React.ReactNode;
}

const COLS: Col[] = [
  { key: "duration_ms", label: "耗时", align: "right", render: (r) => fmtDur(r.duration_ms) },
  { key: "token_input", label: "输入", align: "right", render: (r) => fmtToken(r.token_input) },
  { key: "token_output", label: "输出", align: "right", render: (r) => fmtToken(r.token_output) },
  {
    key: "token_cached",
    label: "缓存",
    align: "right",
    render: (r) => (
      <>
        {fmtToken(r.token_cached)}
        <span className="text-[var(--muted-foreground)]">
          {" "}({fmtPct(cacheHitRate(r.token_cached, r.token_input))})
        </span>
      </>
    ),
  },
  { key: "token_total", label: "总", align: "right", render: (r) => fmtToken(r.token_total) },
  { key: "step_count", label: "steps", align: "right", render: (r) => r.step_count },
  { key: "tool_count", label: "tools", align: "right", render: (r) => r.tool_count },
  { key: "tool_success_rate", label: "成功率", align: "right", render: (r) => fmtPct(r.tool_success_rate) },
  {
    key: "started_at",
    label: "开始",
    render: (r) => <span className="text-[var(--muted-foreground)]">{fmtTs(r.started_at)}</span>,
  },
];

interface RunsTableProps {
  runs: RunMeta[];
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
  onRowClick?: (id: string) => void;
}

export function RunsTable({ runs, sortKey, sortDir, onSort, onRowClick }: RunsTableProps) {
  if (!runs.length)
    return <EmptyState title="无会话" desc="调整筛选,或先跑一个:python -m agent.agentloop" />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>run_id</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>model</TableHead>
          {COLS.map((c) => (
            <TableHead
              key={c.key}
              className={cn("cursor-pointer select-none whitespace-nowrap", c.align === "right" && "text-right")}
              onClick={() => onSort(c.key)}
            >
              <span className={cn("inline-flex items-center gap-1", c.align === "right" && "flex-row-reverse")}>
                {c.label}
                {sortKey === c.key ? (
                  sortDir === "asc" ? (
                    <ArrowUp className="h-3 w-3" />
                  ) : (
                    <ArrowDown className="h-3 w-3" />
                  )
                ) : (
                  <ChevronsUpDown className="h-3 w-3 opacity-30" />
                )}
              </span>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((r) => (
          <TableRow key={r.run_id} className="cursor-pointer" onClick={() => onRowClick?.(r.run_id)}>
            <TableCell className="font-mono text-xs text-[var(--muted-foreground)]">{shortId(r.run_id)}</TableCell>
            <TableCell>
              <StatusBadge status={r.status} />
            </TableCell>
            <TableCell className="text-xs">{r.model}</TableCell>
            {COLS.map((c) => (
              <TableCell key={c.key} className="font-mono text-xs">
                {c.render(r)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
