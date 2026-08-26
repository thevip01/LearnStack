"use client";

import { Play, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { CandidateReview } from "@/components/admin/CandidateReview";
import { SubjectPackages } from "@/components/admin/SubjectPackages";
import { PageHeader, PageShell } from "@/components/shell/Page";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonText } from "@/components/ui/Skeleton";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { describeError } from "@/lib/api";
import { formatDateTime, relativeTime, titleCase, truncateMiddle } from "@/lib/format";
import { useCatalog, useIngestionRuns, useIngestionSources, useMe, useStartIngestionRun } from "@/lib/queries";
import type { IngestionRun, IngestionStage, StageReport } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Mirrored from ingestion.py so a run in flight can show the stages it has not
 * reached yet. The API is authoritative: this list only orders the display.
 */
const STAGE_ORDER: readonly IngestionStage[] = [
  "fetch",
  "parse",
  "clean",
  "chunk",
  "embed",
  "extract",
  "validate",
  "review",
  "build",
  "publish",
] as const;

type Panel = "runs" | "sources" | "candidates" | "packages";

/**
 * The ingestion console.
 *
 * Content enters the platform through a ten-stage pipeline, and this is where an
 * admin watches it. Runs poll while one is in flight, because a run advancing
 * from fetch to publish should not need a manual reload.
 */
export function IngestionView() {
  const { data: user, isLoading: loadingUser } = useMe();
  const { data: catalog } = useCatalog();
  const [subjectId, setSubjectId] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>("runs");

  if (loadingUser) {
    return (
      <PageShell>
        <PageHeader title="Ingestion" />
        <SkeletonText rows={6} />
      </PageShell>
    );
  }

  // Admin-only, and said plainly rather than by silently rendering nothing.
  if (!user?.is_admin) {
    return (
      <PageShell>
        <PageHeader title="Ingestion" />
        <EmptyState
          tone="pending"
          icon={<ShieldAlert className="size-5" aria-hidden />}
          title="Admin access required"
          description={
            user
              ? "This console starts ingestion runs and publishes content, so it is limited to admin accounts."
              : "Sign in with an admin account to reach the ingestion console."
          }
        />
      </PageShell>
    );
  }

  const subjects = (catalog?.domains ?? []).flatMap((domain) => domain.subjects);
  const tabs: TabItem[] = [
    { id: "runs", label: "Runs" },
    { id: "candidates", label: "Review queue" },
    { id: "sources", label: "Sources" },
    { id: "packages", label: "Packages" },
  ];

  return (
    <PageShell>
      <PageHeader
        title="Ingestion"
        subtitle="Fetch, extract, review and publish subject content."
        actions={
          // The packages tab reads every package by definition, so the filter would
          // be a control that changes nothing on the panel below it.
          panel === "packages" ? null : (
            <select
              value={subjectId ?? ""}
              onChange={(event) => setSubjectId(event.target.value || null)}
              aria-label="Filter by subject"
              className="h-7 rounded-md border border-line bg-raised px-2 text-xs text-ink focus:border-accent/50"
            >
              <option value="">All subjects</option>
              {subjects.map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.title}
                </option>
              ))}
            </select>
          )
        }
      />

      <Tabs
        items={tabs}
        active={panel}
        onChange={(id) => setPanel(id as Panel)}
        label="Ingestion sections"
        className="mb-4 border-b border-line"
      />

      {panel === "runs" ? (
        <RunsPanel subjectId={subjectId} />
      ) : panel === "candidates" ? (
        <CandidateReview subjectId={subjectId} />
      ) : panel === "packages" ? (
        <SubjectPackages />
      ) : (
        <SourcesPanel subjectId={subjectId} />
      )}
    </PageShell>
  );
}

function RunsPanel({ subjectId }: { subjectId: string | null }) {
  const { data, isLoading, isError, error } = useIngestionRuns(subjectId);
  const start = useStartIngestionRun(subjectId);
  const toast = useToast();
  const [dryRun, setDryRun] = useState(true);

  async function startRun() {
    try {
      const run = await start.mutateAsync({ dry_run: dryRun });
      toast.push({
        tone: "ok",
        title: dryRun ? "Dry run started" : "Ingestion run started",
        message: `Run ${truncateMiddle(run.id, 20)}`,
      });
    } catch (mutationError) {
      toast.push({ tone: "error", title: "Could not start the run", message: describeError(mutationError).message });
    }
  }

  const runs = data?.runs ?? [];

  return (
    <>
      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-center gap-3 py-pad-sm">
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(event) => setDryRun(event.target.checked)}
              className="size-3.5 accent-current"
            />
            Dry run
          </label>
          <span className="text-2xs text-faint">
            {dryRun
              ? "Runs every stage and reports what would change without writing content."
              : "Writes extracted content and can publish a new version."}
          </span>
          <Button
            variant="primary"
            className="ml-auto"
            loading={start.isPending}
            disabled={!subjectId}
            onClick={startRun}
            title={subjectId ? undefined : "Pick a subject first"}
          >
            <Play className="size-3.5" aria-hidden />
            Start run
          </Button>
        </CardBody>
      </Card>

      {isLoading ? (
        <SkeletonText rows={5} />
      ) : isError ? (
        <EmptyState tone="error" title={`Could not load runs (${describeError(error).title})`} description={describeError(error).message} />
      ) : runs.length === 0 ? (
        <EmptyState
          tone="pending"
          title="No ingestion runs yet"
          description={subjectId ? "Start a dry run to see how this subject's sources behave." : "Pick a subject and start a dry run."}
        />
      ) : (
        <ul className="space-y-2">
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </ul>
      )}
    </>
  );
}

function RunRow({ run }: { run: IngestionRun }) {
  const reports = new Map<string, StageReport>(run.stages.map((stage): [string, StageReport] => [stage.stage, stage]));
  const messages = run.stages.flatMap((stage) => stage.messages.map((message) => ({ stage: stage.stage, message })));

  return (
    <Card as="li">
      <CardHeader
        title={
          <span className="font-mono text-xs" title={run.id}>
            {truncateMiddle(run.id, 24)}
          </span>
        }
        subtitle={`${run.subject_id} · started ${relativeTime(run.started_at)}${
          run.source_ids.length > 0 ? ` · ${run.source_ids.length} sources` : ""
        }`}
        actions={
          <>
            {run.dry_run ? <Badge tone="info">Dry run</Badge> : null}
            <Badge tone={runTone(run.status)} glyph={runGlyph(run.status)}>
              {titleCase(run.status)}
            </Badge>
          </>
        }
      />
      <CardBody className="py-pad-sm">
        <ol className="flex flex-wrap gap-1">
          {STAGE_ORDER.map((stage) => {
            const report = reports.get(stage);
            const state = !report ? "pending" : report.finished_at === null ? "running" : report.ok ? "ok" : "failed";
            return (
              <li
                key={stage}
                title={
                  report
                    ? `${stage}: ${report.items_in} in, ${report.items_out} out, ${report.skipped} skipped`
                    : `${stage}: not reached`
                }
                className={cn(
                  "rounded border px-1.5 py-0.5 text-2xs",
                  state === "ok" && "border-ok/40 bg-ok/10 text-ok",
                  state === "failed" && "border-danger/40 bg-danger/10 text-danger",
                  state === "running" && "border-info/40 bg-info/10 text-info",
                  state === "pending" && "border-line bg-raised text-faint",
                )}
              >
                {stage}
              </li>
            );
          })}
        </ol>
        {messages.length > 0 ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-2xs text-muted hover:text-ink">
              {messages.length} stage {messages.length === 1 ? "message" : "messages"}
            </summary>
            <ul className="mt-1 space-y-0.5">
              {messages.map((entry, index) => (
                <li key={`${entry.stage}-${index}`} className="font-mono text-2xs text-faint">
                  <span className="text-muted">{entry.stage}</span> {entry.message}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {run.finished_at ? (
          <div className="mt-1.5 text-2xs text-faint">Finished {formatDateTime(run.finished_at)}</div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function runTone(status: IngestionRun["status"]): "ok" | "danger" | "info" | "neutral" {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "danger";
  if (status === "running") return "info";
  return "neutral";
}

function runGlyph(status: IngestionRun["status"]): string {
  if (status === "succeeded") return "✔";
  if (status === "failed") return "!";
  if (status === "running") return "▶";
  return "◦";
}

function SourcesPanel({ subjectId }: { subjectId: string | null }) {
  const { data, isLoading, isError, error } = useIngestionSources(subjectId);
  const sources = data?.sources ?? [];

  if (isLoading) return <SkeletonText rows={5} />;
  if (isError) {
    const described = describeError(error);
    return <EmptyState tone="error" title={`Could not load sources (${described.title})`} description={described.message} />;
  }
  if (sources.length === 0) {
    return (
      <EmptyState
        tone="pending"
        title="No sources registered"
        description="A subject package declares where its content comes from; those source specs appear here."
      />
    );
  }

  return (
    <Card className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-2xs">
        <thead>
          <tr className="border-b border-line bg-raised/50">
            {["Source", "Adapter", "Type", "Entrypoint", "Priority", "Last run"].map((heading) => (
              <th key={heading} scope="col" className="px-pad py-1.5 font-semibold text-muted">
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {sources.map((source) => (
            <tr key={source.id} className={cn("hover:bg-raised/40", !source.enabled && "opacity-50")}>
              <th scope="row" className="px-pad py-1.5 text-left font-normal">
                <span className="text-xs text-ink">{source.title}</span>
                <div className="flex items-center gap-1">
                  {source.is_first_party ? <Badge tone="accent">First party</Badge> : null}
                  {!source.enabled ? <Badge tone="neutral">Disabled</Badge> : null}
                  {source.policy.requires_auth ? <Badge tone="warn">Auth</Badge> : null}
                </div>
              </th>
              <td className="px-pad py-1.5 text-muted">{source.adapter}</td>
              <td className="px-pad py-1.5 text-muted">{titleCase(source.source_type)}</td>
              <td className="max-w-[18rem] px-pad py-1.5">
                <span className="block truncate font-mono text-faint" title={source.entrypoint}>
                  {source.entrypoint}
                </span>
              </td>
              <td className="px-pad py-1.5 tabular-nums text-muted">{source.priority}</td>
              <td className="px-pad py-1.5 text-faint">{relativeTime(source.last_run_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
