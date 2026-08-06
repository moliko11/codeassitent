"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { ArrowUp, Square } from "lucide-react";
import { useChat } from "@/context/ChatContext";

/**
 * Composer - the message input box.
 * Ported structure from DeepTutor's ChatComposer + ComposerInput, trimmed to
 * a clean auto-sizing textarea + send/stop button. Enter sends (Shift+Enter
 * for a newline; IME composition is respected).
 */
export default function Composer() {
  const { sendMessage, isStreaming, stopStreaming, messages } = useChat();
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-size the textarea to its content.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // Focus the composer on the empty state.
  useEffect(() => {
    if (messages.length === 0) textareaRef.current?.focus();
  }, [messages.length]);

  const doSend = useCallback(() => {
    const text = value.trim();
    if (!text || isStreaming) return;
    sendMessage(text);
    setValue("");
  }, [value, isStreaming, sendMessage]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Respect IME composition (Enter confirms the candidate, doesn't send).
      if (e.nativeEvent.isComposing) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        doSend();
      }
    },
    [doSend],
  );

  const hasContent = value.trim().length > 0;

  return (
    <div
      className="relative z-20 mx-auto w-full shrink-0 px-6 pb-5"
      style={{ maxWidth: messages.length ? 960 : 768 }}
    >
      {messages.length > 0 && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-transparent to-[var(--background)]/72" />
      )}
      <div className="relative">
        <div className="relative rounded-[26px] border border-[var(--border)]/55 bg-[var(--card)] shadow-[0_1px_2px_rgba(0,0,0,0.025),0_10px_28px_-10px_rgba(0,0,0,0.08)]">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            maxLength={32000}
            placeholder="有问题尽管问我…"
            className="w-full resize-none overflow-hidden bg-transparent px-4 pb-1 pt-3.5 text-[16px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
            style={{ transition: "height 0.15s ease-out", minHeight: 56 }}
          />
          <div className="flex items-center justify-end px-3 pb-2 pt-0.5">
            {isStreaming ? (
              <button
                type="button"
                onClick={stopStreaming}
                className="group relative ml-1 inline-flex h-8 w-8 items-center justify-center rounded-[10px] bg-[var(--primary)] text-[var(--primary-foreground)] transition-transform duration-150 hover:bg-[var(--primary)]/90 active:scale-95"
                aria-label="停止生成"
                title="停止生成"
              >
                <span className="pointer-events-none absolute inset-[3px] rounded-full border-[1.5px] border-white/25 border-t-white/85 animate-spin opacity-90 transition-opacity group-hover:opacity-40" />
                <Square size={10} strokeWidth={2.6} className="relative z-10 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={doSend}
                disabled={!hasContent}
                className="ml-1 inline-flex h-8 w-8 items-center justify-center rounded-[10px] bg-[var(--primary)] text-[var(--primary-foreground)] transition-[background-color,transform,opacity] duration-150 hover:bg-[var(--primary)]/90 active:scale-95 disabled:opacity-25"
                aria-label="发送"
                title="发送"
              >
                <ArrowUp size={16} strokeWidth={2.5} />
              </button>
            )}
          </div>
        </div>
        <p className="mt-2 text-center text-[11px] text-[var(--muted-foreground)]/70">
          模板演示 · 回复为本地模拟 · Enter 发送，Shift+Enter 换行
        </p>
      </div>
    </div>
  );
}
