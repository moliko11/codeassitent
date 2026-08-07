import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  title: string;
  desc?: string;
  icon?: LucideIcon;
}

export function EmptyState({ title, desc, icon: Icon = Inbox }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <Icon className="h-8 w-8 text-[var(--muted-foreground)] opacity-40" />
      <div className="text-sm font-medium">{title}</div>
      {desc && <div className="max-w-sm text-xs text-[var(--muted-foreground)]">{desc}</div>}
    </div>
  );
}
