import { Badge } from "@/components/ui/badge";
import { statusTone, TONE_CLASS } from "@/lib/constants";
import { cn } from "@/lib/cn";

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge className={cn("border-transparent font-medium", TONE_CLASS[statusTone(status)], className)}>
      {status}
    </Badge>
  );
}
