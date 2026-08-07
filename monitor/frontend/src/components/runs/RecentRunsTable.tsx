import { useNavigate } from "react-router-dom";
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

export function RecentRunsTable({ runs }: { runs: RunMeta[] }) {
  const nav = useNavigate();
  if (!runs.length)
    return <EmptyState title="无会话" desc="先跑一个:python -m agent.agentloop(exit 退出)" />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>run_id</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>model</TableHead>
          <TableHead className="text-right">token</TableHead>
          <TableHead className="text-right">缓存%</TableHead>
          <TableHead className="text-right">工具</TableHead>
          <TableHead className="text-right">耗时</TableHead>
          <TableHead>开始</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((r) => (
          <TableRow
            key={r.run_id}
            className="cursor-pointer"
            onClick={() => nav(`/runs/${r.run_id}`)}
          >
            <TableCell className="font-mono text-xs text-[var(--muted-foreground)]">
              {shortId(r.run_id)}
            </TableCell>
            <TableCell>
              <StatusBadge status={r.status} />
            </TableCell>
            <TableCell className="text-xs">{r.model}</TableCell>
            <TableCell className="text-right font-mono text-xs">{fmtToken(r.token_total)}</TableCell>
            <TableCell className="text-right font-mono text-xs">
              {fmtPct(cacheHitRate(r.token_cached, r.token_input))}
            </TableCell>
            <TableCell className="text-right font-mono text-xs">{r.tool_count}</TableCell>
            <TableCell className="text-right font-mono text-xs">{fmtDur(r.duration_ms)}</TableCell>
            <TableCell className="text-xs text-[var(--muted-foreground)]">{fmtTs(r.started_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
