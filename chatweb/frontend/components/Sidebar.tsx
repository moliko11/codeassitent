"use client";

import { useState } from "react";
import {
  BookOpen,
  Brain,
  ChevronDown,
  Github,
  House,
  LayoutGrid,
  Library,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Settings,
  SquarePen,
  type LucideIcon,
} from "lucide-react";
import { useAppShell } from "@/context/AppShellContext";
import { useChat } from "@/context/ChatContext";
import { cn } from "@/lib/cn";

interface NavEntry {
  label: string;
  icon: LucideIcon;
  active?: boolean;
}

const PRIMARY_NAV: NavEntry[] = [
  { label: "Home", icon: House, active: true },
  { label: "Co-Writer", icon: PenLine },
  { label: "Book", icon: Library },
  { label: "Learning Space", icon: LayoutGrid },
];
const SECONDARY_NAV: NavEntry[] = [
  { label: "Memory", icon: Brain },
  { label: "Knowledge", icon: BookOpen },
  { label: "Settings", icon: Settings },
];

const RECENTS_KEY = "chat-template.recentsCollapsed";

function relativeTime(ts: number): string {
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  return `${Math.floor(hr / 24)} 天前`;
}

/**
 * Sidebar - the workspace rail (expanded 220px / collapsed 60px).
 * Ported from DeepTutor's SidebarShell: logo + collapse toggle, primary nav,
 * a "Recents" session list, secondary nav, footer. Capability gating and
 * Next.js routing are removed (single-page template) - nav items are visual.
 */
export default function Sidebar() {
  const { sidebarCollapsed: collapsed, setSidebarCollapsed } = useAppShell();
  const { sessions, activeSessionId, selectSession, newChat } = useChat();
  const [recentsCollapsed, setRecentsCollapsed] = useState(false);

  const toggleRecents = () => {
    const next = !recentsCollapsed;
    setRecentsCollapsed(next);
    try {
      window.localStorage.setItem(RECENTS_KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  /* ---- Collapsed rail ---- */
  if (collapsed) {
    return (
      <aside className="group/sb relative flex h-screen w-[60px] shrink-0 flex-col items-center bg-[var(--secondary)] py-3 transition-all duration-200">
        <div className="relative mb-2 flex h-9 w-9 items-center justify-center">
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="flex items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-all hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
            aria-label="展开侧栏"
          >
            <PanelLeftOpen size={16} />
          </button>
        </div>
        <nav className="mt-1 flex w-full flex-col items-center gap-1 px-1.5">
          {PRIMARY_NAV.map((item) => (
            <button
              key={item.label}
              title={item.label}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150",
                item.active
                  ? "bg-[var(--accent)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]",
              )}
            >
              <item.icon size={18} strokeWidth={item.active ? 2 : 1.6} />
            </button>
          ))}
        </nav>
        <div className="flex-1" />
        <div className="flex w-full flex-col items-center gap-1 px-1.5">
          <div className="my-1 h-px w-7 bg-[var(--border)]/40" />
          {SECONDARY_NAV.map((item) => (
            <button
              key={item.label}
              title={item.label}
              className="flex h-9 w-9 items-center justify-center rounded-xl text-[var(--foreground)]/85 transition-all hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
            >
              <item.icon size={18} strokeWidth={1.6} />
            </button>
          ))}
        </div>
      </aside>
    );
  }

  /* ---- Expanded rail ---- */
  return (
    <aside className="flex h-screen w-[220px] shrink-0 flex-col bg-[var(--secondary)] transition-all duration-200">
      {/* Header: logo + new-chat + collapse */}
      <div className="flex h-14 items-center justify-between px-3">
        <span className="flex items-center gap-1.5 text-[15px] font-semibold text-[var(--foreground)]">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)]">
            <MessageSquare size={14} strokeWidth={2.2} />
          </span>
          Chat
        </span>
        <div className="flex items-center">
          <button
            onClick={newChat}
            title="新对话"
            aria-label="新对话"
            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
          >
            <SquarePen size={15} />
          </button>
          <button
            onClick={() => setSidebarCollapsed(true)}
            title="收起侧栏"
            aria-label="收起侧栏"
            className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <PanelLeftClose size={15} />
          </button>
        </div>
      </div>

      {/* Primary nav */}
      <nav className="px-2 pt-1">
        <div className="space-y-px">
          {PRIMARY_NAV.map((item) => (
            <button
              key={item.label}
              onClick={item.active ? newChat : undefined}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13.5px] transition-colors",
                item.active
                  ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                  : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]",
              )}
            >
              <item.icon size={16} strokeWidth={item.active ? 1.9 : 1.5} />
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      </nav>

      {/* Recents */}
      <section className={cn("mt-3 flex min-h-0 flex-col", recentsCollapsed ? "" : "flex-1")}>
        <button
          type="button"
          onClick={toggleRecents}
          className="mx-2 flex items-center justify-between rounded-md px-2 py-1 text-left text-[11.5px] text-[var(--muted-foreground)]/70 transition-colors hover:bg-[var(--background)]/40 hover:text-[var(--muted-foreground)]"
        >
          <span>Recents</span>
          <ChevronDown
            size={13}
            strokeWidth={1.7}
            className={cn(
              "transition-all",
              recentsCollapsed ? "-rotate-90 opacity-60" : "opacity-60",
            )}
          />
        </button>
        {!recentsCollapsed && (
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 pt-0.5">
            {sessions.map((s) => {
              const active = s.id === activeSessionId;
              return (
                <button
                  key={s.id}
                  onClick={() => selectSession(s.id)}
                  className={cn(
                    "group flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-1.5 text-left transition-colors",
                    active
                      ? "bg-[var(--accent)] text-[var(--foreground)]"
                      : "text-[var(--foreground)]/85 hover:bg-[var(--background)]/60",
                  )}
                >
                  <span className="truncate text-[13px] leading-snug">{s.title}</span>
                  <span className="truncate text-[10.5px] text-[var(--muted-foreground)]">
                    {relativeTime(s.updatedAt)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {recentsCollapsed && <div className="flex-1" />}

      {/* Secondary nav + footer */}
      <div className="border-t border-[var(--border)]/40 px-2 py-2">
        {SECONDARY_NAV.map((item) => (
          <button
            key={item.label}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--foreground)]/85 transition-colors hover:bg-[var(--background)]/60 hover:text-[var(--foreground)]"
          >
            <item.icon size={16} strokeWidth={1.5} />
            <span>{item.label}</span>
          </button>
        ))}
        <div className="mt-1 flex items-center gap-0.5">
          <a
            href="https://github.com/HKUDS/DeepTutor"
            target="_blank"
            rel="noreferrer noopener"
            title="GitHub"
            className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--muted-foreground)]"
          >
            <Github size={13} strokeWidth={1.7} />
          </a>
        </div>
      </div>
    </aside>
  );
}
