// 火焰图选中 span 的详情面板(Phase 3 §3.1)。tool span 提供「在消息流查看」跳转(高亮对应 tool_result)。
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fmtDur, fmtToken } from "@/lib/format";
import type { Span } from "@/lib/types";

interface Props {
  span: Span;
  onJumpToTranscript: (callId: string) => void;
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-[var(--muted-foreground)]">{k}</dt>
      <dd className="font-mono">{v}</dd>
    </>
  );
}

export function SpanDetail({ span, onJumpToTranscript }: Props) {
  const a = span.attrs ?? {};
  const usage = a.usage;
  const rows: [string, string][] = [
    ["类型", span.type],
    ["耗时", fmtDur(span.duration_ms)],
    usage ? ["token", `入${fmtToken(usage.input_tokens)}/出${fmtToken(usage.output_tokens)}${usage.cached_tokens ? `/缓存${fmtToken(usage.cached_tokens)}` : ""}`] : null,
    a.ok === false ? ["结果", "失败"] : a.ok === true ? ["结果", "成功"] : null,
    a.error_type ? ["错误", a.error_type] : null,
    a.attempts && a.attempts > 1 ? ["重试", `${a.attempts - 1} 次`] : null,
    a.call_id ? ["call_id", a.call_id] : null,
    a.agent_id ? ["agent_id", a.agent_id] : null,
    a.summary ? ["summary", a.summary] : null,
  ].filter(Boolean) as [string, string][];

  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--muted)]/40 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">
          {span.type} · {span.name}
        </span>
        {a.agent_id && (
          <Badge className="bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-400 text-[10px]">
            [子] {a.agent_id}
          </Badge>
        )}
        {a.ok === false && (
          <Badge className="bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-400 text-[10px]">
            失败
          </Badge>
        )}
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {rows.map(([k, v]) => (
          <Row key={k} k={k} v={v} />
        ))}
      </dl>
      {span.type === "tool" && a.call_id && (
        <Button
          size="sm"
          variant="outline"
          className="mt-3 h-7 text-xs"
          onClick={() => onJumpToTranscript(a.call_id as string)}
        >
          在消息流查看
        </Button>
      )}
    </div>
  );
}
