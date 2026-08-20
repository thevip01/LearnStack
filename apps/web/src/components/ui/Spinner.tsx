import { cn } from "@/lib/utils";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span
      role="status"
      aria-label={label}
      className={cn("inline-block size-4 animate-spin rounded-full border-2 border-line border-t-accent", className)}
    />
  );
}

export function InlineLoading({ text = "Loading" }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 px-pad py-pad text-xs text-muted">
      <Spinner className="size-3" />
      {text}
    </div>
  );
}
