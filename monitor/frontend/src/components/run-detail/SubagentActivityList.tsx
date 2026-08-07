// 子 Agent 活动列表(Phase 3 §3.2):主 agent 用 Task 工具派子 agent 的每次活动一张卡。
// 数据来自 /api/runs/{id}/subagents(transcript 里 agent_id="subagent" 的连续段聚合)。
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/common/EmptyState";
import { fmtDur, fmtPct, fmtToken } from "@/lib/format";
import type { SubagentActivity } from "@/lib/types";
import { Bot, CheckCircle2, XCircle } from "lucide-react";

export function SubagentActivityList({ activities }: { activities: SubagentActivity[] }) {
  if (!activities.length)
    return (
      <EmptyState
        title="无子 Agent 活动"
        desc="本次 run 没有用 Task 工具派子 agent,或子 agent 事件未落主 transcript"
      />
    );
  return (
    <div className="space-y-2">
      {activities.map((a) => (
        <ActivityCard key={a.id} a={a} />
      ))}
    </div>
  );
}

function ActivityCard({ a }: { a: SubagentActivity }) {
  return (
    <div className="rounded-md border border-[var(--border)] p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Bot className="h-4 w-4 shrink-0 text-amber-500" />
        <span className="font-mono font-semibold">子 Agent #{a.id + 1}</span>
        <span className="text-xs text-[var(--muted-foreground)]">耗时 {fmtDur(a.duration_ms)}</span>
        <span className="text-xs text-[var(--muted-foreground)]">token {fmtToken(a.token_total)}</span>
        <span className="text-xs text-[var(--muted-foreground)]">
          {a.step_count} 步
        </span>
        {a.tool_count > 0 && (
          <Badge
            variant="outline"
            className={
              a.tool_success_rate === 1
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400"
                : "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400"
            }
          >
            {a.tool_success_count}/{a.tool_count} 工具成功 ({fmtPct(a.tool_success_rate)})
          </Badge>
        )}
      </div>
      <div className="mt-1 text-[11px] text-[var(--muted-foreground)]">
        {new Date(a.start_ts * 1000).toLocaleString("zh-CN", { hour12: false })} →{" "}
        {new Date(a.end_ts * 1000).toLocaleString("zh-CN", { hour12: false })}
      </div>
      {a.output && (
        <pre className="mt-2 max-h-40 overflow-auto rounded bg-[var(--muted)]/50 p-2 text-[11px] whitespace-pre-wrap break-all">
          {a.output}
        </pre>
      )}
      {a.tool_calls.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {a.tool_calls.map((tc, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]"
            >
              {tc.ok ? (
                <CheckCircle2 className="h-3 w-3 text-emerald-500" />
              ) : (
                <XCircle className="h-3 w-3 text-rose-500" />
              )}
              <span className="font-mono">{tc.tool_name}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
