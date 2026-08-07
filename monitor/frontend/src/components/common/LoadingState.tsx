import { Skeleton } from "@/components/ui/skeleton";

export function LoadingState({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={className}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="mb-2 h-8 w-full" />
      ))}
    </div>
  );
}

export function CardSkeleton({ className }: { className?: string }) {
  return <Skeleton className={className} />;
}
