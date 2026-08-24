"use client";

import { Library } from "lucide-react";
import { SubjectCard } from "@/components/catalog/SubjectCard";
import { PageHeader, PageShell } from "@/components/shell/Page";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonCards } from "@/components/ui/Skeleton";
import { describeError } from "@/lib/api";
import { useCatalog } from "@/lib/queries";

/**
 * The catalogue.
 *
 * Domains and subjects are read straight from `/catalog` and grouped by whatever
 * the API returns. There is no hardcoded domain list, so publishing a new
 * subject package makes it appear here with no frontend change.
 */
export function CatalogView() {
  const { data, isLoading, isError, error } = useCatalog();

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Subjects" subtitle="Loading the catalogue…" />
        <SkeletonCards count={6} />
      </PageShell>
    );
  }

  if (isError) {
    const described = describeError(error);
    return (
      <PageShell>
        <PageHeader title="Subjects" />
        <EmptyState
          tone="error"
          title={`Could not load the catalogue (${described.title})`}
          description={described.message}
        />
      </PageShell>
    );
  }

  // A domain with no published subjects is noise on the shelf, not a section.
  const domains = (data?.domains ?? []).filter((domain) => domain.subjects.length > 0);
  const total = domains.reduce((sum, domain) => sum + domain.subjects.length, 0);

  if (total === 0) {
    return (
      <PageShell>
        <PageHeader title="Subjects" />
        <EmptyState
          tone="pending"
          icon={<Library className="size-5" aria-hidden />}
          title="No subjects published yet"
          description="Once a subject package is ingested and published it shows up here. The runtime needs no code change to host it."
        />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Subjects"
        subtitle={`${total} published across ${domains.length} ${domains.length === 1 ? "domain" : "domains"}`}
      />
      <div className="space-y-7">
        {domains.map((domain) => (
          <section key={domain.id}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{domain.title}</h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {domain.subjects.map((subject) => (
                <SubjectCard key={subject.id} subject={subject} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </PageShell>
  );
}
