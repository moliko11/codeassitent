"use client";

import { useState } from "react";
import { Check, Palette } from "lucide-react";
import { useAppShell } from "@/context/AppShellContext";
import type { Theme } from "@/lib/theme";
import { cn } from "@/lib/cn";

const THEMES: { id: Theme; label: string }[] = [
  { id: "snow", label: "Default" },
  { id: "light", label: "Cream" },
  { id: "dark", label: "Dark" },
  { id: "glass", label: "Glass" },
];

/** Small popover to switch the four themes. Drop into the header or sidebar. */
export default function ThemeSwitcher() {
  const { theme, setTheme } = useAppShell();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="切换主题"
        title="切换主题"
        className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
      >
        <Palette size={16} strokeWidth={1.7} />
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="dt-popup-up absolute right-0 top-full z-50 mt-1.5 w-[180px] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg backdrop-blur-md">
            {THEMES.map((t) => {
              const active = theme === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    setTheme(t.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[12.5px] transition-colors",
                    active
                      ? "bg-[var(--primary)]/[0.06] text-[var(--primary)]"
                      : "text-[var(--foreground)] hover:bg-[var(--muted)]/45",
                  )}
                >
                  <span className="flex-1">{t.label}</span>
                  {active && <Check size={14} strokeWidth={2} />}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
