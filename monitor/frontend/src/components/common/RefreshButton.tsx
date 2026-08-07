// 手动刷新按钮(Phase 3 §3.4):列表页 refetchInterval 轮询之外的手动兜底。busy 时转圈并禁用。
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export function RefreshButton({ onClick, busy }: { onClick: () => void; busy?: boolean }) {
  return (
    <Button size="sm" variant="outline" onClick={onClick} disabled={busy}>
      <RefreshCw className={cn("h-3 w-3", busy && "animate-spin")} />
      刷新
    </Button>
  );
}
