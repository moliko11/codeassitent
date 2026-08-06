"use client";

import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { ToolCallView } from "@/lib/types";

const phaseMeta: Record<ToolCallView["phase"], { icon: typeof Loader2; cls: string; label: string }> = {
  producing: { icon: Loader2, cls: "text-[var(--muted-foreground)] animate-spin", label: "生成参数" },
  running: { icon: Loader2, cls: "text-[var(--primary)] animate-spin", label: "执行中" },
  done: { icon: CheckCircle2, cls: "text-emerald-500", label: "完成" },
  error: { icon: XCircle, cls: "text-red-500", label: "失败" },
};

function tryParse(s: string): object | undefined {
  try { return JSON.parse(s); } catch { return undefined; }
}

/**
 * ToolCallCard - 工具调用卡片(对齐 chat-template-integration §7)。
 * 展示 phase 状态(产参/执行/完成)+ 参数 JSON + summary + 耗时 + 重试次数。
 */
export default function ToolCallCard({ tc }: { tc: ToolCallView }) {
  const m = phaseMeta[tc.phase];
  const Icon = m.icon;
  const args = tc.arguments ?? (tc.argumentsJson ? tryParse(tc.argumentsJson) : undefined);
  return (
    <div className="my-1.5 rounded-lg border border-[var(--border)]/60 bg-[var(--card)]/60 px-3 py-2 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2">
        <Icon size={13} className={m.cls} />
        <span className="font-mono font-medium text-[var(--foreground)]">{tc.toolName}</span>
        <span className="text-[var(--muted-foreground)]">{m.label}</span>
        {tc.attempts != null && tc.attempts > 1 && (
          <span className="text-[var(--muted-foreground)]">重试 {tc.attempts - 1} 次</span>
        )}
        {tc.elapsedMs != null && (
          <span className="text-[var(--muted-foreground)]">{Math.round(tc.elapsedMs)}ms</span>
        )}
      </div>
      {args && (
        <pre className="mt-1 max-h-40 overflow-auto rounded bg-[var(--muted)]/40 p-1.5 text-[11px] leading-snug text-[var(--foreground)]/80">
{JSON.stringify(args, null, 2)}
        </pre>
      )}
      {tc.summary && (
        <div className="mt-1 line-clamp-3 text-[var(--muted-foreground)]">{tc.summary}</div>
      )}
    </div>
  );
}
