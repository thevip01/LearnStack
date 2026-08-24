"use client";

import { ArrowRight, LineChart, Sparkles } from "lucide-react";
import Link from "next/link";
import { PageHeader, PageShell } from "@/components/shell/Page";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonText } from "@/components/ui/Skeleton";
import { describeError } from "@/lib/api";
import { formatMinutes, formatScore, titleCase } from "@/lib/format";
import { useRecommendations, useSubjectRuntime } from "@/lib/queries";
import { routes, targetRoute } from "@/lib/routes";
import { themeCssVars } from "@/lib/theme";
import type { LearningMode, SubjectRuntimeOut } from "@/lib/types";

/**
 * The subject front page: what this package contains and every way into it.
 *
 * Modes are listed from `runtime.modes`, not from a hardcoded list, and each one
 * links at the workspace URL for that mode. A mode the package declares but has
 * not laid out is shown as unavailable instead of being quietly dropped.
 */
export function SubjectOverview({ subjectId }: { subjectId: string }) {
  const { data: runtime, isLoading, isError, error } = useSubjectRuntime(subjectId);

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Loading subject…" back={{ href: routes.subjects, label: "All subjects" }} />
        <SkeletonText rows={6} />
      </PageShell>
    );
  }

  if (isError || !runtime) {
    const described = describeError(error);
    return (
      <PageShell>
        <PageHeader title="Subject" back={{ href: routes.subjects, label: "All subjects" }} />
        <EmptyState
          tone="error"
          title={described.code === "not_found" ? `No subject "${subjectId}"` : `Could not load subject (${described.title})`}
          description={described.message}
        />
      </PageShell>
    );
  }

  const entryMode = preferredMode(runtime);
  const overall = runtime.progress?.summary.overall ?? null;

  return (
    <div style={themeCssVars(runtime.theme)} className="flex min-h-0 flex-1 flex-col">
      <PageShell>
        <PageHeader
          title={runtime.title}
          subtitle={runtime.subtitle ?? runtime.domain.title}
          back={{ href: routes.subjects, label: "All subjects" }}
          actions={
            <>
              <Link
                href={routes.progress(runtime.id)}
                className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-raised px-2.5 text-xs text-muted hover:border-accent/50 hover:text-ink"
              >
                <LineChart className="size-3.5" aria-hidden />
                {overall === null ? "Progress" : `${formatScore(overall)} overall`}
              </Link>
              <Link
                href={routes.workspace(runtime.id, entryMode)}
                className="inline-flex h-7 items-center gap-1.5 rounded-md border border-accent bg-accent px-2.5 text-xs font-medium text-canvas hover:bg-accent/90"
              >
                Open {titleCase(entryMode)}
                <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </>
          }
        />

        <div className="mb-5 flex flex-wrap items-center gap-1.5">
          <Badge tone="neutral">{runtime.domain.title}</Badge>
          <Badge tone="neutral" title={`Content hash ${runtime.content_hash}`}>
            v{runtime.version}
          </Badge>
          {runtime.provider ? <Badge tone="neutral">{runtime.provider}</Badge> : null}
          {runtime.status !== "published" ? <Badge tone="warn">{titleCase(runtime.status)}</Badge> : null}
          <Badge tone="neutral">{runtime.skills.length} skills</Badge>
        </div>

        <p className="mb-6 max-w-3xl text-xs leading-relaxed text-muted">{runtime.description}</p>

        <ModeGrid runtime={runtime} />
        <Recommendations subjectId={runtime.id} />
        <Curriculum runtime={runtime} />
      </PageShell>
    </div>
  );
}

/** The default mode unless the package never laid it out. */
function preferredMode(runtime: SubjectRuntimeOut): LearningMode {
  if (runtime.mode_layouts[runtime.default_mode]) return runtime.default_mode;
  return runtime.modes.find((mode) => runtime.mode_layouts[mode]) ?? runtime.default_mode;
}

function ModeGrid({ runtime }: { runtime: SubjectRuntimeOut }) {
  return (
    <section className="mb-6">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Ways in</h2>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {runtime.modes.map((mode) => {
          const layout = runtime.mode_layouts[mode];
          if (!layout) {
            return (
              <Card as="li" key={mode} className="p-pad opacity-60">
                <div className="text-sm font-medium text-muted">{titleCase(mode)}</div>
                <p className="mt-1 text-2xs text-faint">Declared by this package but not laid out yet.</p>
              </Card>
            );
          }
          return (
            <Card as="li" key={mode} className="transition-colors hover:border-accent/50">
              <Link href={routes.workspace(runtime.id, mode)} className="block p-pad">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-ink">{layout.label ?? titleCase(mode)}</span>
                  <ArrowRight className="size-3.5 text-faint" aria-hidden />
                </div>
                <p className="mt-1 text-2xs text-faint">
                  {layout.panels.length} {layout.panels.length === 1 ? "panel" : "panels"} · primary {layout.primary_slot}
                </p>
              </Link>
            </Card>
          );
        })}
      </ul>
    </section>
  );
}

function Recommendations({ subjectId }: { subjectId: string }) {
  const { data } = useRecommendations(subjectId, 4);
  const items = data?.recommendations ?? [];
  if (items.length === 0) return null;

  return (
    <section className="mb-6">
      <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        <Sparkles className="size-3.5" aria-hidden />
        Do next
      </h2>
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li key={`${item.kind}-${item.id}`}>
            <Link
              href={targetRoute(subjectId, item.kind, item.id)}
              className="flex items-start justify-between gap-3 rounded-panel border border-line bg-surface px-pad py-pad-sm hover:border-accent/50"
            >
              <div className="min-w-0">
                <div className="truncate text-xs font-medium text-ink">{item.title}</div>
                {/* The recommender's sentence, rendered verbatim, never recomposed here. */}
                <div className="mt-0.5 text-2xs text-faint">{item.reason}</div>
              </div>
              <Badge tone="accent">{titleCase(item.kind)}</Badge>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Curriculum({ runtime }: { runtime: SubjectRuntimeOut }) {
  if (runtime.tracks.length === 0) return null;

  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Curriculum</h2>
      <div className="space-y-3">
        {runtime.tracks.map((track) => (
          <Card key={track.id}>
            <CardHeader title={track.title} subtitle={track.goal ?? track.summary ?? undefined} />
            <CardBody className="py-pad-sm">
              <ul className="divide-y divide-line">
                {track.modules.map((module) => (
                  <li key={module.id} className="flex items-center justify-between gap-3 py-1.5">
                    <span className="min-w-0 truncate text-xs text-ink">{module.title}</span>
                    <span className="shrink-0 text-2xs text-faint">
                      {module.concepts.length} concepts
                      {module.labs.length > 0 ? ` · ${module.labs.length} labs` : ""}
                      {module.estimated_minutes ? ` · ${formatMinutes(module.estimated_minutes)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        ))}
      </div>
    </section>
  );
}
