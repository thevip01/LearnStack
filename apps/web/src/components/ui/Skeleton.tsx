import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton-bar h-3 w-full", className)} />;
}

/** Text-shaped placeholder: rows of decreasing width read as prose, not as a bug. */
export function SkeletonText({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-label="Loading content">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className={index === rows - 1 ? "w-2/3" : "w-full"} />
      ))}
    </div>
  );
}

export function SkeletonTree({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-1.5 p-pad" role="status" aria-label="Loading navigation">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn("h-4", index % 3 === 0 ? "w-3/4" : "w-full", index % 3 === 2 && "ml-3 w-2/3")}
        />
      ))}
    </div>
  );
}

export function SkeletonCards({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, index) => (
        <div key={index} className="space-y-3 rounded-panel border border-line bg-surface p-pad">
          <Skeleton className="h-4 w-2/3" />
          <SkeletonText rows={2} />
          <Skeleton className="h-2 w-1/3" />
        </div>
      ))}
    </div>
  );
}
