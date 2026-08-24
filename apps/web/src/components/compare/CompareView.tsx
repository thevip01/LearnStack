"use client";

import { GitCompare, X } from "lucide-react";
import Link from "next/link";
import { PageHeader, PageShell } from "@/components/shell/Page";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonText } from "@/components/ui/Skeleton";
import { describeError } from "@/lib/api";
import { DASH, titleCase } from "@/lib/format";
import { useCompare } from "@/lib/queries";
import { routes } from "@/lib/routes";

/**
 * Side-by-side concept comparison.
 *
 * The facet rows come from the API, not from a fixed list here: comparing two
 * cloud services and comparing two sorting algorithms surface different facets,
 * and neither shape is hardcoded in the frontend.
 */
export function CompareView({ ids }: { ids: string[] }) {
  const { data, isLoading, isError, error } = useCompare(ids);

  if (ids.length < 2) {
    return (
      <PageShell>
        <PageHeader title="Compare" />
        <EmptyState
          tone="pending"
          icon={<GitCompare className="size-5" aria-hidden />}
          title="Pick at least two concepts"
          description="Comparison takes concept ids in the URL, for example /compare?ids=s3,ebs. Open a concept and use its compare action to build this list."
          actions={
            <Link
              href={routes.subjects}
              className="inline-flex h-7 items-center rounded-md border border-line bg-raised px-2.5 text-xs text-ink hover:border-accent/50"
            >
              Browse subjects
            </Link>
          }
        />
      </PageShell>
    );
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Compare" subtitle={ids.join(" vs ")} />
        <SkeletonText rows={8} />
      </PageShell>
    );
  }

  if (isError || !data) {
    const described = describeError(error);
    return (
      <PageShell>
        <PageHeader title="Compare" subtitle={ids.join(" vs ")} />
        <EmptyState tone="error" title={`Could not compare (${described.title})`} description={described.message} />
      </PageShell>
    );
  }

  const { concepts, rows } = data;

  if (concepts.length === 0) {
    return (
      <PageShell>
        <PageHeader title="Compare" />
        <EmptyState
          tone="pending"
          title="None of those concepts resolved"
          description={`Nothing matched ${ids.join(", ")}. Concept ids are package-scoped, so check the subject they belong to.`}
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Compare"
        subtitle={`${concepts.length} concepts · ${rows.length} facets`}
        actions={
          <div className="flex flex-wrap gap-1">
            {concepts.map((concept) => {
              const remaining = concepts.filter((other) => other.id !== concept.id).map((other) => other.id);
              return (
                <Link
                  key={concept.id}
                  href={remaining.length >= 2 ? routes.compare(remaining) : routes.compare([])}
                  className="inline-flex h-6 items-center gap-1 rounded border border-line bg-raised px-1.5 text-2xs text-muted hover:border-danger/50 hover:text-danger"
                  title={`Remove ${concept.title} from the comparison`}
                >
                  {concept.title}
                  <X className="size-3" aria-hidden />
                </Link>
              );
            })}
          </div>
        }
      />

      <Card className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-line bg-raised/50">
              <th scope="col" className="sticky left-0 z-10 w-40 bg-raised/95 px-pad py-2 font-semibold text-muted">
                Facet
              </th>
              {concepts.map((concept) => (
                <th key={concept.id} scope="col" className="min-w-48 px-pad py-2 align-bottom">
                  <Link
                    href={routes.workspace(concept.subject_id, "learn", concept.id)}
                    className="font-semibold text-ink hover:text-accent"
                  >
                    {concept.title}
                  </Link>
                  <div className="mt-0.5 text-2xs font-normal text-faint">{titleCase(concept.category)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((row) => (
              <tr key={row.facet} className="align-top hover:bg-raised/40">
                <th scope="row" className="sticky left-0 z-10 bg-surface px-pad py-2 font-medium text-muted">
                  {row.facet}
                </th>
                {concepts.map((concept) => {
                  const value = row.values[concept.id];
                  return (
                    <td key={concept.id} className="px-pad py-2 leading-relaxed">
                      {value ? (
                        <span className="text-ink/90">{value}</span>
                      ) : (
                        <span className="text-faint" title="Not stated for this concept">
                          {DASH}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </PageShell>
  );
}
