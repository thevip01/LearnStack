"use client";

import Link from "next/link";
import { SubjectRuntime } from "@/components/runtime/SubjectRuntime";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineLoading } from "@/components/ui/Spinner";
import { describeError } from "@/lib/api";
import { formatMinutes, titleCase } from "@/lib/format";
import { useSubjectRuntime } from "@/lib/queries";
import { routes } from "@/lib/routes";
import type { LearningMode } from "@/lib/types";

/**
 * Fetches the package and hands it to the generic runtime.
 *
 * This is the last place that knows anything about routing: below it the runtime
 * reads its layout, panels and theme from `SubjectRuntimeOut`. Nothing here
 * branches on which subject is open: the only checks are "does this package
 * exist" and "does it publish this mode".
 */
export function WorkspaceView({
  subjectId,
  mode,
  nodeId,
}: {
  subjectId: string;
  mode: LearningMode;
  nodeId: string | null;
}) {
  const { data: runtime, isLoading, isError, error } = useSubjectRuntime(subjectId);

  if (isLoading) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <InlineLoading text="Opening workspace" />
      </div>
    );
  }

  if (isError || !runtime) {
    const described = describeError(error);
    return (
      <EmptyState
        tone="error"
        title={described.code === "not_found" ? `No subject "${subjectId}"` : `Could not open the workspace (${described.title})`}
        description={described.message}
        actions={
          <Link
            href={routes.subjects}
            className="inline-flex h-7 items-center rounded-md border border-line bg-raised px-2.5 text-xs text-ink hover:border-accent/50"
          >
            Back to subjects
          </Link>
        }
      />
    );
  }

  // The URL can name a real mode this particular package does not publish.
  if (!runtime.modes.includes(mode)) {
    return (
      <EmptyState
        tone="pending"
        title={`${runtime.title} has no "${mode}" mode`}
        description={`This package publishes ${runtime.modes.map((available) => titleCase(available)).join(", ")}.`}
        actions={
          <>
            {runtime.modes.map((available) => (
              <Link
                key={available}
                href={routes.workspace(runtime.id, available, nodeId)}
                className="inline-flex h-7 items-center rounded-md border border-line bg-raised px-2.5 text-xs text-ink hover:border-accent/50"
              >
                {titleCase(available)}
              </Link>
            ))}
          </>
        }
      >
        <div className="text-2xs text-faint">
          {runtime.navigation.length} items · {formatMinutes(estimatedMinutes(runtime.navigation))} of material
        </div>
      </EmptyState>
    );
  }

  return <SubjectRuntime runtime={runtime} mode={mode} nodeId={nodeId} />;
}

function estimatedMinutes(items: Array<{ estimated_minutes: number | null }>): number {
  return items.reduce((sum, item) => sum + (item.estimated_minutes ?? 0), 0);
}
