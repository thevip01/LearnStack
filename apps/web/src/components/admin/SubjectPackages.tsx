"use client";

import { PackagePlus, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphTile } from "@/components/ui/GlyphTile";
import { SkeletonText } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { describeError } from "@/lib/api";
import { useCatalog, useReloadSubjects, useValidateSubject } from "@/lib/queries";
import type { SubjectReloadOut, SubjectValidateOut } from "@/lib/types";

/**
 * Where a new subject enters a running install.
 *
 * There is no upload, and that is the design rather than a gap. A subject is a
 * directory of authored JSON under `subjects/`, version controlled like code and
 * loaded by the registry at boot; the platform holds no truth about a subject that
 * the package does not state. So "import" is two steps that this page makes
 * visible: put the directory on disk, then tell the running API to re-read disk.
 * Everything the rest of the app draws, the six mastery axes, the layouts, the
 * skill graph, the search index, is rebuilt from what that reload loaded.
 *
 * The reason this is worth a UI at all is the failure case. A reload reports which
 * packages loaded and which were refused, with the reason per package, and a
 * refused package leaves its previous version serving traffic. Doing this over curl
 * hides exactly the part you needed to see.
 */
export function SubjectPackages() {
  const { data: catalog, isLoading } = useCatalog();
  const reload = useReloadSubjects();
  const validate = useValidateSubject();
  const toast = useToast();
  const [report, setReport] = useState<SubjectReloadOut | null>(null);
  const [checked, setChecked] = useState<Record<string, SubjectValidateOut>>({});
  const [checking, setChecking] = useState<string | null>(null);

  const subjects = (catalog?.domains ?? []).flatMap((domain) =>
    domain.subjects.map((subject) => ({ ...subject, domain: domain.title })),
  );

  async function runReload() {
    try {
      const result = await reload.mutateAsync();
      setReport(result);
      setChecked({});
      toast.push({
        tone: result.failed.length > 0 ? "error" : "ok",
        title: result.failed.length > 0 ? "Reloaded, with refusals" : "Packages reloaded",
        message:
          result.failed.length > 0
            ? `${result.loaded.length} loaded, ${result.failed.length} refused. The refused packages kept their previous version.`
            : `${result.loaded.length} ${result.loaded.length === 1 ? "package" : "packages"} re-read from disk and reindexed.`,
      });
    } catch (error) {
      toast.push({ tone: "error", title: "Reload failed", message: describeError(error).message });
    }
  }

  async function runValidate(subjectId: string) {
    setChecking(subjectId);
    try {
      const result = await validate.mutateAsync(subjectId);
      setChecked((previous) => ({ ...previous, [subjectId]: result }));
    } catch (error) {
      toast.push({ tone: "error", title: `Could not validate ${subjectId}`, message: describeError(error).message });
    } finally {
      setChecking(null);
    }
  }

  return (
    <>
      <Card className="mb-4">
        <CardHeader
          title="Import a subject"
          subtitle="A package on disk, then one reload. No deploy, no restart, no schema migration."
          actions={
            <Button variant="primary" loading={reload.isPending} onClick={runReload}>
              <RefreshCw className="size-3.5" aria-hidden />
              Reload from disk
            </Button>
          }
        />
        <CardBody className="py-pad-sm">
          <ol className="space-y-1.5 text-2xs text-muted">
            <Step n={1}>
              Put the package directory in <code className="font-mono text-faint">subjects/</code>, beside{" "}
              <code className="font-mono text-faint">programming.python</code>. It is checked in like code, so a subject
              arrives through a pull request and its history is the repository&apos;s history.
            </Step>
            <Step n={2}>
              Press reload. The registry re-reads every package, swaps in the ones that validate, re-mirrors the cache
              and reindexes search. A package that fails validation is refused and named below, and the version already
              loaded keeps serving.
            </Step>
            <Step n={3}>
              Validate any subject to see the soft checks it passed without having to satisfy. Warnings are the ones
              worth fixing that were never worth blocking on.
            </Step>
          </ol>
        </CardBody>
      </Card>

      {report ? <ReloadReport report={report} /> : null}

      {isLoading ? (
        <SkeletonText rows={4} />
      ) : subjects.length === 0 ? (
        <EmptyState
          tone="pending"
          icon={<PackagePlus className="size-5" aria-hidden />}
          title="No packages loaded"
          description="Nothing in subjects/ validated. Reload to see the reason for each refusal."
        />
      ) : (
        <ul className="space-y-2">
          {subjects.map((subject) => (
            <Card as="li" key={subject.id}>
              <CardBody className="py-pad-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <GlyphTile icon={subject.theme?.icon} title={subject.title} size="sm" />
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium text-ink">{subject.title}</div>
                    <div className="truncate font-mono text-2xs text-faint" title={subject.id}>
                      {subject.id} · {subject.domain}
                    </div>
                  </div>
                  <Badge tone="neutral" title="Declared by the package, not by the platform">
                    v{subject.version}
                  </Badge>
                  <Button
                    size="xs"
                    variant="outline"
                    className="ml-auto"
                    loading={checking === subject.id}
                    onClick={() => runValidate(subject.id)}
                  >
                    Validate
                  </Button>
                </div>
                {checked[subject.id] ? <ValidateResult result={checked[subject.id]!} /> : null}
              </CardBody>
            </Card>
          ))}
        </ul>
      )}
    </>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-2">
      <span className="mt-px flex size-4 shrink-0 items-center justify-center rounded-full border border-line font-mono text-[10px] text-faint">
        {n}
      </span>
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** What the last reload did. Kept on screen until the next one, since it is the receipt. */
function ReloadReport({ report }: { report: SubjectReloadOut }) {
  return (
    <Card className="mb-4">
      <CardHeader
        title="Last reload"
        subtitle={`${report.loaded.length} loaded, ${report.failed.length} refused`}
        actions={
          report.failed.length > 0 ? (
            <Badge tone="danger" glyph="!">
              Refusals
            </Badge>
          ) : (
            <Badge tone="ok" glyph="✔">
              Clean
            </Badge>
          )
        }
      />
      <CardBody className="space-y-2 py-pad-sm">
        <ul className="flex flex-wrap gap-1">
          {report.loaded.map((id) => (
            <li key={id} className="rounded border border-ok/40 bg-ok/10 px-1.5 py-0.5 font-mono text-2xs text-ok">
              {id}
            </li>
          ))}
        </ul>
        {report.failed.map((failure) => (
          <div key={failure.id} className="rounded border border-danger/40 bg-danger/5 p-pad-sm">
            <div className="flex items-center gap-1.5 font-mono text-2xs text-danger">
              <TriangleAlert className="size-3" aria-hidden />
              {failure.id}
            </div>
            <ul className="mt-1 space-y-0.5">
              {failure.problems.map((problem, index) => (
                <li key={index} className="text-2xs text-muted">
                  {problem}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function ValidateResult({ result }: { result: SubjectValidateOut }) {
  const clean = result.problems.length === 0 && result.warnings.length === 0;
  return (
    <div className="mt-2 border-t border-line pt-2">
      {clean ? (
        <p className="flex items-center gap-1.5 text-2xs text-ok">
          <ShieldCheck className="size-3" aria-hidden />
          No problems, no warnings.
        </p>
      ) : (
        <ul className="space-y-1">
          {result.problems.map((problem, index) => (
            <li key={`p-${index}`} className="text-2xs text-danger">
              <span className="mr-1 font-semibold uppercase">problem</span>
              {problem}
            </li>
          ))}
          {result.warnings.map((warning, index) => (
            <li key={`w-${index}`} className="text-2xs text-warn">
              <span className="mr-1 font-semibold uppercase">warning</span>
              {warning}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
