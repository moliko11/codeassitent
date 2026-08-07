import type * as React from "react";
import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

interface KpiCardProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: LucideIcon;
  className?: string;
}

export function KpiCard({ label, value, sub, icon: Icon, className }: KpiCardProps) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-[var(--muted-foreground)]">{label}</span>
        {Icon && <Icon className="h-4 w-4 text-[var(--muted-foreground)]" />}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-[var(--muted-foreground)]">{sub}</div>}
    </Card>
  );
}
