import { Spinner } from "@/components/ui/Spinner";

/**
 * Shown while a server page resolves its params. Every view already renders its
 * own skeleton for the data fetch, so this covers only the brief gap before the
 * client view mounts: a spinner, not a fake layout.
 */
export default function Loading() {
  return (
    <div className="flex h-full min-h-0 items-center justify-center p-6">
      <span className="inline-flex items-center gap-2 text-xs text-muted">
        <Spinner />
        Loading
      </span>
    </div>
  );
}
