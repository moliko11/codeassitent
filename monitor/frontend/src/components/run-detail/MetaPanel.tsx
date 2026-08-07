import type * as React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { StatusBadge } from "@/components/common/StatusBadge";
import { fmtTs, fmtDur, fmtToken, fmtPct, cacheHitRate } from "@/lib/format";
import type { RunMeta, RunReport, Trace } from "@/lib/types";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-[var(--muted-foreground)]">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium">{children}</dd>
    </div>
  );
}

interface Props {
  meta: RunMeta;
  report: RunReport | null;
  trace?: Trace | null;
}

export function MetaPanel({ meta, report, trace }: Props) {
  // 主/子工具数:从 trace tool span 的 agent_id 拆(无=主循环,有=子 agent)
  let mainTools = 0;
  let subTools = 0;
  if (trace) {
    for (const s of trace.spans) {
      if (s.type !== "tool") continue;
      if (s.attrs?.agent_id) subTools++;
      else mainTools++;
    }
  }
  const toolSplit = trace ? `主 ${mainTools} / 子 ${subTools}` : `${meta.tool_count}`;

  return (
    <Card>
      <CardContent className="p-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
          <Field label="状态 / model">
            <div className="flex items-center gap-2">
              <StatusBadge status={meta.status} />
              <span className="text-xs text-[var(--muted-foreground)]">{meta.model}</span>
            </div>
          </Field>
          <Field label="耗时">{fmtDur(meta.duration_ms)}</Field>
          <Field label="开始">{fmtTs(meta.started_at)}</Field>
          <Field label="结束">{fmtTs(meta.ended_at)}</Field>
          <Field label="输入 token">{fmtToken(meta.token_input)}</Field>
          <Field label="输出 token">{fmtToken(meta.token_output)}</Field>
          <Field label="缓存命中">
            {fmtToken(meta.token_cached)}{" "}
            <span className="text-xs text-[var(--muted-foreground)]">
              ({fmtPct(cacheHitRate(meta.token_cached, meta.token_input))})
            </span>
          </Field>
          <Field label="总 token">{fmtToken(meta.token_total)}</Field>
          <Field label="steps / tools">
            {meta.step_count} / {toolSplit}
          </Field>
          <Field label="成功率">{fmtPct(meta.tool_success_rate)}</Field>
          {report ? (
            <>
              <Field label="avg latency">{fmtDur(report.avg_tool_latency_ms)}</Field>
              <Field label="超时 / 重试">
                {report.timeout_count} / {report.retry_count}
              </Field>
            </>
          ) : (
            <Field label="trace 详情">
              <span className="text-xs font-normal text-[var(--muted-foreground)]">
                无 trace(崩了没 RunEnd,仅 run_meta 摘要)
              </span>
            </Field>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}
