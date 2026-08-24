"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, PageShell } from "@/components/shell/Page";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineLoading } from "@/components/ui/Spinner";
import { describeError } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { useSearch } from "@/lib/queries";
import { routes, targetRoute } from "@/lib/routes";
import type { SearchResult } from "@/lib/types";

const DEBOUNCE_MS = 250;

/**
 * Search.
 *
 * Typing queries live against a debounced term, while the URL is only rewritten
 * on submit, so the address stays a stable, shareable thing rather than
 * thrashing history on every keystroke.
 */
export function SearchView({ initialQuery }: { initialQuery: string }) {
  const router = useRouter();
  const [term, setTerm] = useState(initialQuery);
  const [debounced, setDebounced] = useState(initialQuery);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(term), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [term]);

  const { data, isFetching, isError, error } = useSearch(debounced);
  const results = data?.results ?? [];
  const tooShort = debounced.trim().length <= 1;

  return (
    <PageShell>
      <PageHeader
        title="Search"
        subtitle="Concepts, practice tasks, projects and skills across every published subject."
      />

      <form
        className="mb-5"
        onSubmit={(event) => {
          event.preventDefault();
          const next = term.trim();
          if (next.length > 1) router.replace(routes.search(next));
        }}
      >
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" aria-hidden />
          {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
          <input
            autoFocus
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search for a concept, an error message, a task…"
            aria-label="Search query"
            className="h-9 w-full rounded-md border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-faint focus:border-accent/50"
          />
        </div>
      </form>

      {tooShort ? (
        <EmptyState
          tone="pending"
          icon={<Search className="size-5" aria-hidden />}
          title="Type at least two characters"
          description="Search matches titles, keywords, body prose and the error text attached to debugging tasks."
        />
      ) : isError ? (
        <EmptyState tone="error" title={`Search failed (${describeError(error).title})`} description={describeError(error).message} />
      ) : results.length === 0 && !isFetching ? (
        <EmptyState
          tone="pending"
          title={`Nothing matches "${debounced.trim()}"`}
          description="Try a shorter phrase, or the exact wording of an error message."
        />
      ) : (
        <>
          <div className="mb-2 flex items-center gap-2 text-2xs text-faint">
            <span>
              {results.length} {results.length === 1 ? "result" : "results"}
            </span>
            {isFetching ? <InlineLoading text="Searching" /> : null}
          </div>
          <ul className="space-y-1.5">
            {results.map((result) => (
              <ResultRow key={`${result.kind}-${result.subject_id}-${result.id}`} result={result} />
            ))}
          </ul>
        </>
      )}
    </PageShell>
  );
}

function ResultRow({ result }: { result: SearchResult }) {
  return (
    <li>
      <Link
        href={targetRoute(result.subject_id, result.kind, result.id)}
        className="block rounded-panel border border-line bg-surface px-pad py-pad-sm hover:border-accent/50"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-xs font-medium text-ink">{result.title}</div>
            <p className="mt-0.5 line-clamp-2 text-2xs leading-relaxed text-muted">{result.snippet}</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <Badge tone="accent">{titleCase(result.kind)}</Badge>
            <span className="text-2xs text-faint" title="Which field matched">
              {titleCase(result.matched_on)}
            </span>
          </div>
        </div>
        <div className="mt-1 truncate text-2xs text-faint">{result.subject_id}</div>
      </Link>
    </li>
  );
}
