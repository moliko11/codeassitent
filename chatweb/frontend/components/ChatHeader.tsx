"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { History, Pencil } from "lucide-react";
import ThemeSwitcher from "./ThemeSwitcher";
import { useChat } from "@/context/ChatContext";

// FileHistoryPanel 模块级 import monacoSetup(浏览器副作用),必须 dynamic ssr:false,
// 否则静态链会把 monaco-editor 拉进 SSG 预渲染(window is not defined)。
const FileHistoryPanel = dynamic(() => import("./FileHistoryPanel"), { ssr: false });

/**
 * ChatHeader - the slim title bar above the message column.
 * Ported structure from DeepTutor's home page header (editable session title
 * + action buttons), trimmed to: editable title + theme switcher.
 * Phase 2 §2.5:「文件历史」按钮打开 diff 面板(无 activeSessionId 时禁用)。
 */
export default function ChatHeader({
  title,
  onRename,
}: {
  title: string;
  onRename: (next: string) => void;
}) {
  const { activeSessionId } = useChat();
  const [showFiles, setShowFiles] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);

  const commit = () => {
    const next = draft.trim() || title;
    setDraft(next);
    if (next !== title) onRename(next);
    setEditing(false);
  };

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[var(--border)]/60 px-4">
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setDraft(title);
              setEditing(false);
            }
          }}
          className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-transparent px-2 py-1 text-[15px] font-medium text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setDraft(title);
            setEditing(true);
          }}
          className="group flex min-w-0 flex-1 items-center gap-1.5 text-left"
          title="重命名"
        >
          <span className="truncate text-[15px] font-medium text-[var(--foreground)]">
            {title}
          </span>
          <Pencil
            size={13}
            strokeWidth={1.7}
            className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover:opacity-100"
          />
        </button>
      )}
      <button
        type="button"
        onClick={() => setShowFiles(true)}
        disabled={!activeSessionId}
        className="flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 disabled:cursor-not-allowed disabled:opacity-40"
        title={activeSessionId ? "查看文件历史 diff" : "开始对话后才能查看文件历史"}
      >
        <History size={14} />
        <span className="hidden sm:inline">文件历史</span>
      </button>
      <ThemeSwitcher />
      {showFiles && activeSessionId && (
        <FileHistoryPanel runId={activeSessionId} onClose={() => setShowFiles(false)} />
      )}
    </header>
  );
}
