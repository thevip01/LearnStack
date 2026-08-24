import Link from "next/link";
import { routes } from "@/lib/routes";

/**
 * Reached when a subject id does not resolve or a mode is not a real
 * `LearningMode`. Both are ordinary outcomes of a hand-edited URL, so this reads
 * as information rather than as a failure.
 */
export default function NotFound() {
  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="w-full max-w-md rounded-panel border border-dashed border-line-strong bg-surface/60 p-5">
        <div className="text-2xs uppercase tracking-widest text-faint">404</div>
        <h1 className="mt-1 text-sm font-semibold text-ink">Nothing lives at this address</h1>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">
          The subject, concept or mode in this URL does not exist. Ids are scoped to the subject package that defines
          them, so a link copied between subjects will not resolve.
        </p>
        <div className="mt-4 flex justify-center gap-2">
          <Link
            href={routes.subjects}
            className="inline-flex h-7 items-center rounded-md border border-accent bg-accent px-2.5 text-xs font-medium text-canvas hover:bg-accent/90"
          >
            Browse subjects
          </Link>
          <Link
            href={routes.search()}
            className="inline-flex h-7 items-center rounded-md border border-line bg-raised px-2.5 text-xs text-ink hover:border-accent/50"
          >
            Search
          </Link>
        </div>
      </div>
    </div>
  );
}
