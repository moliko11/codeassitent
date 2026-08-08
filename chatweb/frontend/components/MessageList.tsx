"use client";

import { memo, useState } from "react";
import { Check, Copy, Sparkles, XCircle } from "lucide-react";
import { useChat } from "@/context/ChatContext";
import { useChatAutoScroll } from "@/lib/useChatAutoScroll";
import type { ChatMessage, ToolCallView, TokenUsage } from "@/lib/types";
import MarkdownRenderer from "./MarkdownRenderer";
import ToolCallCard from "./ToolCallCard";

const SUGGESTIONS = [
  "用通俗的语言解释一下傅里叶变换",
  "帮我写一个 React 防抖 Hook",
  "动量守恒定律的适用条件是什么？",
  "总结一下 TypeScript 泛型的常见用法",
];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-[var(--muted-foreground)] opacity-0 transition-all hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)] group-hover/msg:opacity-100"
      aria-label="复制"
    >
      {copied ? <Check size={12} strokeWidth={2} /> : <Copy size={12} strokeWidth={1.7} />}
      {copied ? "已复制" : "复制"}
    </button>
  );
}

// 整轮总账(turn 结束才显示,对齐 CC result.usage;不再逐条 assistant 消息显示 per-step usage)
function TurnSummary({ usage, durationMs, numSteps }: {
  usage: TokenUsage; durationMs?: number; numSteps?: number;
}) {
  const cached = usage.cached_tokens
    ? ` · cache ${Math.round((usage.cached_tokens / (usage.input_tokens || 1)) * 100)}%`
    : "";
  const steps = numSteps ? ` · ${numSteps} 步` : "";
  const dur = durationMs ? ` · ${durationMs.toFixed(0)}ms` : "";
  return (
    <div className="mt-1.5 text-[10.5px] text-[var(--muted-foreground)]/70">
      本轮 in:{usage.input_tokens} out:{usage.output_tokens}{cached}{steps}{dur}
    </div>
  );
}

interface RowProps {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  toolCalls?: ToolCallView[];
  turnUsage?: TokenUsage;
  durationMs?: number;
  numSteps?: number;
  streaming?: boolean;
  status?: "running" | "completed" | "failed";
}

const MessageRow = memo(function MessageRow({ role, content, thinking, toolCalls, turnUsage, durationMs, numSteps, streaming, status }: RowProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-[var(--secondary)] px-4 py-2.5 text-[15px] leading-relaxed text-[var(--foreground)]">
          {content}
        </div>
      </div>
    );
  }

  // 正在思考:流式中且还没文本/工具
  const isThinking = !!streaming && !content.trim() && !(toolCalls && toolCalls.length);
  return (
    <div className="group/msg flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
        <Sparkles size={15} strokeWidth={1.8} />
      </div>
      <div className="min-w-0 flex-1">
        {isThinking ? (
          <div className="flex items-center gap-2 py-1.5 text-[13px] text-[var(--muted-foreground)]">
            <span className="dt-breathing-text">正在思考…</span>
          </div>
        ) : (
          <>
            {thinking && (
              <details className="mb-1.5 rounded-lg border border-[var(--border)]/40 bg-[var(--muted)]/20 px-3 py-1.5">
                <summary className="cursor-pointer text-[12px] text-[var(--muted-foreground)]">
                  思考过程
                </summary>
                <div className="mt-1 whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
                  {thinking}
                </div>
              </details>
            )}
            {toolCalls && toolCalls.length > 0 && (
              <div className="mb-1">
                {toolCalls.map((tc) => (
                  <ToolCallCard key={tc.callId} tc={tc} />
                ))}
              </div>
            )}
            {content && (
              <>
                <MarkdownRenderer content={content} className="text-[var(--foreground)]" />
                {/* Phase 1 §1.4:流式打字光标(内容已有时的块状光标闪烁) */}
                {streaming && <span className="dt-typing-cursor" aria-hidden="true" />}
              </>
            )}
            {/* Phase 1 §1.4:失败差异化(网络/后端错误时挂红条,区别于工具级失败) */}
            {status === "failed" && (
              <div className="mt-1.5 flex items-start gap-1.5 rounded-lg border border-red-500/30 bg-red-500/5 px-2.5 py-1.5 text-[12px] text-red-500/90">
                <XCircle size={13} className="mt-0.5 shrink-0" />
                <span>本轮出错{content ? "" : "，请检查后端服务后重试"}</span>
              </div>
            )}
            <div className="mt-1 flex items-center gap-3">
              {!streaming && content && <CopyButton text={content} />}
            </div>
            {/* turn 结束才显示整轮 token 总账(对齐 CC result),不逐条消息显示 */}
            {turnUsage && !streaming && (
              <TurnSummary usage={turnUsage} durationMs={durationMs} numSteps={numSteps} />
            )}
          </>
        )}
      </div>
    </div>
  );
});

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--primary)]/10 text-[var(--primary)]">
        <Sparkles size={26} strokeWidth={1.7} />
      </div>
      <h1 className="text-[26px] font-semibold tracking-tight text-[var(--foreground)]">
        有什么可以帮你的？
      </h1>
      <p className="mt-2 text-[14px] text-[var(--muted-foreground)]">
        接入 code/agent 真实后端 · 支持工具调用 / 思考过程 / token 用量
      </p>
      <div className="mt-7 grid w-full max-w-[640px] grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-left text-[13.5px] text-[var(--foreground)] transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--muted)]/30"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function MessageList({
  onPickSuggestion,
}: {
  onPickSuggestion: (text: string) => void;
}) {
  const { messages, isStreaming } = useChat();
  const scrollRef = useChatAutoScroll([
    messages.length,
    messages.length ? messages[messages.length - 1].content : "",
    isStreaming,
  ]);

  if (messages.length === 0) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto">
        <EmptyState onPick={onPickSuggestion} />
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      data-chat-scroll-root="true"
      className="min-h-0 flex-1 overflow-y-auto"
    >
      <div className="mx-auto flex max-w-[820px] flex-col gap-6 px-6 py-6">
        {messages.map((m: ChatMessage) => (
          <MessageRow
            key={m.id}
            role={m.role}
            content={m.content}
            thinking={m.thinking}
            toolCalls={m.toolCalls}
            turnUsage={m.turnUsage}
            durationMs={m.durationMs}
            numSteps={m.numSteps}
            streaming={m.streaming}
            status={m.status}
          />
        ))}
      </div>
    </div>
  );
}
