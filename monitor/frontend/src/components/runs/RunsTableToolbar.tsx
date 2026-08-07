// 筛选 toolbar:status / model 多选 chip toggle(从 runs 派生可选项)
import { cn } from "@/lib/cn";
import { statusTone, TONE_CLASS } from "@/lib/constants";
import type { RunMeta } from "@/lib/types";

function toggle(set: Set<string>, v: string, onSet: (s: Set<string>) => void) {
  const n = new Set(set);
  if (n.has(v)) n.delete(v);
  else n.add(v);
  onSet(n);
}

function unique(arr: string[]): string[] {
  return Array.from(new Set(arr.filter(Boolean)));
}

interface Props {
  runs: RunMeta[];
  statusFilter: Set<string>;
  onStatusFilter: (s: Set<string>) => void;
  modelFilter: Set<string>;
  onModelFilter: (s: Set<string>) => void;
}

export function RunsTableToolbar({
  runs,
  statusFilter,
  onStatusFilter,
  modelFilter,
  onModelFilter,
}: Props) {
  const statuses = unique(runs.map((r) => r.status));
  const models = unique(runs.map((r) => r.model));

  return (
    <div className="flex flex-wrap items-center gap-4">
      {statuses.length > 1 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-[var(--muted-foreground)]">状态</span>
          {statuses.map((s) => {
            const active = statusFilter.has(s);
            return (
              <button
                key={s}
                onClick={() => toggle(statusFilter, s, onStatusFilter)}
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
                  active
                    ? TONE_CLASS[statusTone(s)]
                    : "border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]",
                )}
              >
                {s}
              </button>
            );
          })}
        </div>
      )}
      {models.length > 1 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-[var(--muted-foreground)]">model</span>
          {models.map((m) => {
            const active = modelFilter.has(m);
            return (
              <button
                key={m}
                onClick={() => toggle(modelFilter, m, onModelFilter)}
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
                  active
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]",
                )}
              >
                {m}
              </button>
            );
          })}
        </div>
      )}
      {(statusFilter.size > 0 || modelFilter.size > 0) && (
        <button
          onClick={() => {
            onStatusFilter(new Set());
            onModelFilter(new Set());
          }}
          className="text-xs text-[var(--primary)] hover:underline"
        >
          清除筛选
        </button>
      )}
    </div>
  );
}
