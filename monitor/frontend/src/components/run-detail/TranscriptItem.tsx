import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { TranscriptRecord } from "@/lib/types";
import { User, Bot, Wrench, Flag } from "lucide-react";

function SubagentBadge({ agentId }: { agentId?: string | null }) {
  if (!agentId) return null;
  return (
    <Badge className="bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400 text-[10px]">
      [{agentId}]
    </Badge>
  );
}

function resultSummary(r: NonNullable<TranscriptRecord["result"]>): string {
  if (r.text) return r.text;
  if (r.data == null) return "";
  return typeof r.data === "string" ? r.data : JSON.stringify(r.data);
}

export function TranscriptItem({
  record: r,
  highlight,
}: {
  record: TranscriptRecord;
  /** 火焰图「在消息流查看」跳转:匹配的 tool_result 高亮(Phase 3 §3.1) */
  highlight?: boolean;
}) {
  if (r.type === "user") {
    return (
      <div className="flex gap-2 rounded-md px-2 py-1.5 hover:bg-[var(--muted)]/40">
        <User className="mt-0.5 h-4 w-4 shrink-0 text-[var(--primary)]" />
        <div className="min-w-0 flex-1 text-sm">
          <SubagentBadge agentId={r.agent_id} /> <span className="font-medium">user:</span>{" "}
          <span className="whitespace-pre-wrap break-words">{r.content}</span>
        </div>
      </div>
    );
  }

  if (r.type === "assistant") {
    const tcs = r.tool_calls ?? [];
    const batch = tcs.length > 1;
    return (
      <div className="flex gap-2 rounded-md px-2 py-1.5 hover:bg-[var(--muted)]/40">
        <Bot className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
        <div className="min-w-0 flex-1 text-sm">
          <SubagentBadge agentId={r.agent_id} /> <span className="font-medium">assistant:</span>
          {r.text && <div className="mt-0.5 whitespace-pre-wrap break-words">{r.text}</div>}
          {batch && (
            <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">
              ┌ 并行 {tcs.length} 个: [{tcs.map((tc) => tc.tool_name).join(", ")}]
            </div>
          )}
          {tcs.map((tc, i) => (
            <div key={i} className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              ⏺ {tc.tool_name}(
              <span className="text-[var(--primary)]">
                {tc.arguments ? JSON.stringify(tc.arguments) : ""}
              </span>
              )
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (r.type === "tool_result") {
    const res = r.result;
    if (!res) return null;
    const summ = resultSummary(res);
    const long = summ.length > 100;
    return (
      <Collapsible
        data-call-id={res.call_id ?? undefined}
        className={cn(
          "flex gap-2 rounded-md px-2 py-1 hover:bg-[var(--muted)]/40",
          highlight && "bg-[var(--muted)]/60 ring-2 ring-indigo-400",
        )}
      >
        <Wrench className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1 text-sm">
          <SubagentBadge agentId={r.agent_id} />
          <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <span className="shrink-0">⎿ {res.tool_name}</span>
            <span
              className={
                res.ok
                  ? "shrink-0 text-emerald-600 dark:text-emerald-400"
                  : "shrink-0 text-rose-600 dark:text-rose-400"
              }
            >
              {res.ok ? "✓" : "✗"}
            </span>
            <span className="truncate">{summ.slice(0, 100)}</span>
            {long && (
              <span className="shrink-0 text-[var(--primary)] hover:underline">展开</span>
            )}
          </CollapsibleTrigger>
          {long && (
            <CollapsibleContent>
              <pre className="mt-1 max-h-60 overflow-auto rounded bg-[var(--muted)] p-2 text-[11px] whitespace-pre-wrap break-all">
                {summ}
              </pre>
            </CollapsibleContent>
          )}
        </div>
      </Collapsible>
    );
  }

  if (r.type === "run_end") {
    return (
      <div className="flex gap-2 rounded-md px-2 py-1.5">
        <Flag className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
        <div className="text-xs text-[var(--muted-foreground)]">
          <SubagentBadge agentId={r.agent_id} /> run_end: {r.status}
        </div>
      </div>
    );
  }
  return null;
}
