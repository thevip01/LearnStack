"use client";

import { GitCompare, LineChart } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { ModeSwitcher } from "@/components/shell/ModeSwitcher";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatScore } from "@/lib/format";
import { routes } from "@/lib/routes";
import { useWorkspaceStore } from "@/lib/store";
import { themeCssVars } from "@/lib/theme";
import type { LearningMode, SubjectRuntimeOut } from "@/lib/types";
import { LayoutRenderer } from "./LayoutRenderer";
import { firstSelectableNode, useWorkspaceNav } from "./nav";

/**
 * The generic runtime.
 *
 * Everything below this component is driven by `SubjectRuntimeOut`: the theme
 * becomes CSS custom properties on this subtree, the mode list comes from the
 * package, and the workspace itself is whatever `mode_layouts[mode]` declares.
 * There is no subject-specific branch here or anywhere beneath it.
 */
export function SubjectRuntime({
  runtime,
  mode,
  nodeId,
}: {
  runtime: SubjectRuntimeOut;
  mode: LearningMode;
  nodeId: string | null;
}) {
  const setContext = useWorkspaceStore((state) => state.setContext);
  const { goToMode, goToNode } = useWorkspaceNav(runtime.id, mode);
  const layout = runtime.mode_layouts[mode] ?? null;

  useEffect(() => {
    setContext({ subjectId: runtime.id, mode, nodeId });
  }, [mode, nodeId, runtime.id, setContext]);

  // A mode with no selection lands on the first thing a learner can open, so a
  // bare /subjects/x/learn is never an empty workspace.
  useEffect(() => {
    if (nodeId) return;
    const first = firstSelectableNode(runtime.navigation);
    if (first) goToNode(first.id);
  }, [goToNode, nodeId, runtime.navigation]);

  const overall = runtime.progress?.summary.overall ?? null;

  return (
    <div style={themeCssVars(runtime.theme)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface px-pad py-1.5">
        <Link href={routes.subject(runtime.id)} className="truncate text-sm font-semibold text-ink hover:text-accent">
          {runtime.title}
        </Link>
        <span className="truncate text-2xs text-faint">{runtime.domain.title}</span>
        <Badge tone="neutral" title={`Content hash ${runtime.content_hash}`}>
          v{runtime.version}
        </Badge>
        {runtime.provider ? <Badge tone="neutral">{runtime.provider}</Badge> : null}

        <div className="ml-auto flex items-center gap-2">
          {overall !== null ? (
            <Link
              href={routes.progress(runtime.id)}
              className="inline-flex items-center gap-1.5 rounded border border-line bg-raised px-1.5 py-0.5 text-2xs text-muted hover:border-accent/50 hover:text-ink"
            >
              <LineChart className="size-3" aria-hidden />
              {formatScore(overall)} overall
            </Link>
          ) : null}
          <Link
            href={routes.compare([runtime.id])}
            className="inline-flex items-center gap-1.5 rounded border border-line bg-raised px-1.5 py-0.5 text-2xs text-muted hover:border-accent/50 hover:text-ink"
          >
            <GitCompare className="size-3" aria-hidden />
            Compare
          </Link>
        </div>

        <div className="basis-full md:basis-auto md:order-last md:ml-3">
          <ModeSwitcher
            modes={runtime.modes}
            layouts={runtime.mode_layouts}
            active={mode}
            onSelect={(next) => goToMode(next, nodeId)}
          />
        </div>
      </div>

      {layout ? (
        <LayoutRenderer runtime={runtime} mode={mode} layout={layout} nodeId={nodeId} />
      ) : (
        <EmptyState
          tone="pending"
          title={`No layout for "${mode}"`}
          description={`This subject publishes ${runtime.modes.join(", ")}. Pick one of those modes to open a workspace.`}
        />
      )}
    </div>
  );
}
