"use client";

import { RotateCw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { routes } from "@/lib/routes";

/**
 * The last line of defence. Panels and views already render their own error
 * states from `describeError`, so anything that reaches here is a render-time
 * fault rather than a failed request, hence the reset button instead of a
 * retry, and the digest, which is the only handle on a server-side stack.
 */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Nothing is wired to a reporter yet; the console keeps the stack reachable.
    console.error("Unhandled render error", error);
  }, [error]);

  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="w-full max-w-md rounded-panel border border-danger/40 bg-surface/60 p-5">
        <h1 className="text-sm font-semibold text-danger">This view failed to render</h1>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">
          The rest of the app is still fine: only this route stopped. Retrying re-renders it without a full reload.
        </p>
        {error.message ? (
          <p className="mt-2 break-words rounded border border-line bg-canvas px-2 py-1.5 font-mono text-2xs text-muted">
            {error.message}
          </p>
        ) : null}
        {error.digest ? <p className="mt-1.5 font-mono text-2xs text-faint">digest {error.digest}</p> : null}
        <div className="mt-4 flex justify-center gap-2">
          <button
            type="button"
            onClick={reset}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-accent bg-accent px-2.5 text-xs font-medium text-canvas hover:bg-accent/90"
          >
            <RotateCw className="size-3.5" aria-hidden />
            Try again
          </button>
          <Link
            href={routes.subjects}
            className="inline-flex h-7 items-center rounded-md border border-line bg-raised px-2.5 text-xs text-ink hover:border-accent/50"
          >
            Back to subjects
          </Link>
        </div>
      </div>
    </div>
  );
}
