import { cn } from "@/lib/cn";
import { spanTypeMeta } from "@/lib/constants";
import { fmtDur } from "@/lib/format";
import type { Span } from "@/lib/types";

interface Props {
  span: Span;
  depth: number;
  runDur: number;
  byParent: Map<string | null, Span[]>;
}

export function FlameBar({ span, depth, runDur, byParent }: Props) {
  const meta = spanTypeMeta(span.type);
  const isSub = !!span.attrs?.agent_id;
  const usage = span.attrs?.usage;
  const widthPct = Math.max(((span.duration_ms ?? 0) / runDur) * 100, 2);
  const children = byParent.get(span.span_id) ?? [];

  const label = `${span.type} ${span.name}${isSub ? " [子]" : ""}`;
  const tip = [
    label,
    `耗时 ${fmtDur(span.duration_ms)}`,
    usage
      ? `token 入${usage.input_tokens}/出${usage.output_tokens}${usage.cached_tokens ? `/缓存${usage.cached_tokens}` : ""}`
      : null,
    span.attrs?.ok === false
      ? `失败${span.attrs.error_type ? ": " + span.attrs.error_type : ""}`
      : null,
    span.attrs?.attempts && span.attrs.attempts > 1
      ? `重试 ${span.attrs.attempts - 1} 次`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div>
      <div style={{ paddingLeft: depth * 14 }}>
        <div
          title={tip}
          className={cn(
            "flex h-6 items-center truncate rounded-sm px-2 text-[11px] text-white",
            meta.bg,
            isSub && "ring-2 ring-rose-500 ring-offset-1 ring-offset-[var(--card)]",
          )}
          style={{ width: `${widthPct}%`, minWidth: "40px" }}
        >
          <span className="truncate">{label}</span>
        </div>
      </div>
      {children.length > 0 && (
        <div className="space-y-0.5">
          {children.map((c) => (
            <FlameBar
              key={c.span_id}
              span={c}
              depth={depth + 1}
              runDur={runDur}
              byParent={byParent}
            />
          ))}
        </div>
      )}
    </div>
  );
}
