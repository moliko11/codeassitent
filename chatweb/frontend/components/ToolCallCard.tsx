"use client";

import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronUp, Loader2, ShieldAlert, XCircle } from "lucide-react";
import type { ToolCallView } from "@/lib/types";

const phaseMeta: Record<ToolCallView["phase"], { icon: typeof Loader2; cls: string; label: string }> = {
  producing: { icon: Loader2, cls: "text-[var(--muted-foreground)] animate-spin", label: "生成参数" },
  running: { icon: Loader2, cls: "text-[var(--primary)] animate-spin", label: "执行中" },
  done: { icon: CheckCircle2, cls: "text-emerald-500", label: "完成" },
  error: { icon: XCircle, cls: "text-red-500", label: "失败" },
};

// Phase 1 §1.3:错误分类 -> 图标 + 文案(guardrail 拒绝常见,单独配色提示)
const ERROR_META: Record<string, { icon: typeof Loader2; label: string; cls: string }> = {
  GuardrailBlocked: { icon: ShieldAlert, label: "安全拦截", cls: "text-amber-500" },
  CircuitOpen: { icon: ShieldAlert, label: "熔断", cls: "text-orange-500" },
  ToolNotFound: { icon: XCircle, label: "工具不存在", cls: "text-red-500" },
  SchemaValidationError: { icon: XCircle, label: "参数校验失败", cls: "text-red-500" },
};

const SUMMARY_CLAMP_CHARS = 120; // 摘要超此长度默认折叠,点击展开(Phase 1 §1.3)

function tryParse(s: string): object | undefined {
  try { return JSON.parse(s); } catch { return undefined; }
}

/**
 * ToolCallCard - 工具调用卡片(对齐 chat-template-integration §7)。
 * 展示 phase 状态(产参/执行/完成)+ 参数 JSON + summary + 耗时 + 重试次数。
 * Phase 1 §1.3:失败时按 errorType 分类展示(安全拦截/熔断/校验失败…),长摘要可展开/折叠。
 */
export default function ToolCallCard({ tc }: { tc: ToolCallView }) {
  const m = phaseMeta[tc.phase];
  const Icon = m.icon;
  const args = tc.arguments ?? (tc.argumentsJson ? tryParse(tc.argumentsJson) : undefined);
  const errMeta = tc.errorType ? ERROR_META[tc.errorType] : undefined;
  const [expanded, setExpanded] = useState(false);
  // summary 太长 -> 折叠;展开逻辑(summary.length > 阈值)才给展开按钮
  const longSummary = !!tc.summary && tc.summary.length > SUMMARY_CLAMP_CHARS;
  const showClamped = !!tc.summary && longSummary && !expanded;
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
      {/* Phase 1 §1.3:失败分类(错误类型图标 + 中文标签 + 原因) */}
      {tc.phase === "error" && (
        <div className="mt-1 flex items-start gap-1.5 rounded bg-red-500/10 px-2 py-1 text-[12px]">
          {errMeta ? <errMeta.icon size={12} className={`mt-0.5 shrink-0 ${errMeta.cls}`} /> : <XCircle size={12} className="mt-0.5 shrink-0 text-red-500" />}
          <div className="min-w-0">
            <span className={`font-medium ${errMeta?.cls ?? "text-red-500"}`}>
              {errMeta?.label ?? tc.errorType ?? "执行失败"}
            </span>
            {tc.errorMessage && (
              <span className="block break-words text-[var(--muted-foreground)]">{tc.errorMessage}</span>
            )}
          </div>
        </div>
      )}
      {args && (
        <pre className="mt-1 max-h-40 overflow-auto rounded bg-[var(--muted)]/40 p-1.5 text-[11px] leading-snug text-[var(--foreground)]/80">
{JSON.stringify(args, null, 2)}
        </pre>
      )}
      {tc.summary && (
        <div className="mt-1">
          <div className={`text-[var(--muted-foreground)] ${showClamped ? "line-clamp-3" : ""}`}>
            {tc.summary}
          </div>
          {longSummary && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-0.5 flex items-center gap-0.5 text-[11px] text-[var(--primary)] hover:underline"
            >
              {expanded ? (
                <>
                  <ChevronUp size={11} /> 收起
                </>
              ) : (
                <>
                  <ChevronDown size={11} /> 展开
                </>
              )}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
