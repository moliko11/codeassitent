"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useChat } from "@/context/ChatContext";

/**
 * ApprovalDialog - HITL 批准弹窗(阶段0 Phase A)。
 * 后端 can_use_tool 推 ApprovalRequestEvent -> ChatContext.queueApproval 设 pendingApproval ->
 * 本组件渲染工具名/原因/参数,Allow 放行 / Deny 拒绝。点完 POST /api/approve/{id} 解后端 future。
 * 60s 无响应自动拒绝(ChatContext 内 setTimeout)。
 */
export default function ApprovalDialog() {
  const { pendingApproval, resolveApproval } = useChat();
  if (!pendingApproval) return null;

  const { requestId, toolName, reason, arguments: args } = pendingApproval;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]">
      <div className="w-[min(90vw,480px)] rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-2xl">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-500">
            <ShieldAlert size={18} strokeWidth={2} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-semibold text-[var(--foreground)]">需人工批准</h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              工具{" "}
              <span className="rounded bg-[var(--muted)]/60 px-1.5 py-0.5 font-mono text-[12px] text-[var(--foreground)]">
                {toolName}
              </span>{" "}
              需要你的确认:
            </p>
          </div>
        </div>

        <div className="mt-3 rounded-xl border border-[var(--border)]/60 bg-[var(--muted)]/30 p-3">
          <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-[var(--foreground)]/90">
            {reason}
          </p>
          {args && Object.keys(args).length > 0 && (
            <pre className="mt-2 max-h-44 overflow-auto rounded-lg bg-[var(--background)]/70 p-2.5 text-[11.5px] leading-snug text-[var(--foreground)]/75">
              {JSON.stringify(args, null, 2)}
            </pre>
          )}
        </div>

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => resolveApproval(requestId, false, "用户拒绝执行")}
            className="inline-flex items-center gap-1.5 rounded-[10px] border border-[var(--border)] px-4 py-2 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/40"
          >
            <ShieldCheck size={15} strokeWidth={2} className="text-red-500" />
            拒绝
          </button>
          <button
            type="button"
            onClick={() => resolveApproval(requestId, true)}
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-colors hover:bg-[var(--primary)]/90"
          >
            <ShieldCheck size={15} strokeWidth={2} />
            允许执行
          </button>
        </div>
      </div>
    </div>
  );
}
