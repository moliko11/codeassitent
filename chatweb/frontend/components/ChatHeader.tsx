"use client";

import { useState } from "react";
import { Pencil } from "lucide-react";
import ThemeSwitcher from "./ThemeSwitcher";

/**
 * ChatHeader - the slim title bar above the message column.
 * Ported structure from DeepTutor's home page header (editable session title
 * + action buttons), trimmed to: editable title + theme switcher.
 */
export default function ChatHeader({
  title,
  onRename,
}: {
  title: string;
  onRename: (next: string) => void;
}) {
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
      <ThemeSwitcher />
    </header>
  );
}
