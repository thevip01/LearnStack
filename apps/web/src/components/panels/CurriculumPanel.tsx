"use client";

import { CheckCircle2, Circle, FileText, FlaskConical, GraduationCap, Hammer } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { PanelBody, PanelHint, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { buildNavTree, type NavTreeNode } from "@/components/runtime/nav";
import type { PanelProps } from "@/components/runtime/types";
import { formatMinutes } from "@/lib/format";
import { routes } from "@/lib/routes";
import type { LearningMode, NavigationItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The table of contents. Rebuilds the tree from the flattened `navigation` and
 * links each leaf to `?node=`. The current node is the URL's, so highlighting
 * needs no local state and a deep link paints correctly on first render.
 */
export function CurriculumPanel({ runtime, mode, nodeId }: PanelProps) {
  const tree = buildNavTree(runtime.navigation);

  if (tree.length === 0) {
    return <PanelHint title="No curriculum" description="This subject package declares no navigation tree." />;
  }

  return (
    <>
      <PanelToolbar>
        <span className="text-2xs font-semibold uppercase tracking-wide text-faint">Curriculum</span>
        <span className="ml-auto text-2xs text-faint">{runtime.navigation.length} items</span>
      </PanelToolbar>
      <PanelBody className="p-2">
        <ul className="space-y-0.5">
          {tree.map((node) => (
            <TreeRow key={node.item.id} node={node} subjectId={runtime.id} mode={mode} activeId={nodeId} />
          ))}
        </ul>
      </PanelBody>
    </>
  );
}

const KIND_ICON: Record<NavigationItem["kind"], ReactNode> = {
  track: <GraduationCap className="size-3.5" aria-hidden />,
  module: <FileText className="size-3.5" aria-hidden />,
  concept: <Circle className="size-3 fill-current opacity-40" aria-hidden />,
  project: <Hammer className="size-3.5" aria-hidden />,
  assessment: <CheckCircle2 className="size-3.5" aria-hidden />,
  lab: <FlaskConical className="size-3.5" aria-hidden />,
};

function TreeRow({
  node,
  subjectId,
  mode,
  activeId,
}: {
  node: NavTreeNode;
  subjectId: string;
  mode: LearningMode;
  activeId: string | null;
}) {
  const { item, children } = node;
  const isContainer = item.kind === "track" || item.kind === "module";
  const active = item.id === activeId;
  const indent = { paddingLeft: `${item.depth * 0.75 + 0.25}rem` };

  const inner = (
    <span className="flex min-w-0 items-center gap-2">
      <span className={cn("shrink-0", active ? "text-accent" : "text-faint")}>{KIND_ICON[item.kind]}</span>
      <span className="min-w-0 flex-1 truncate">{item.title}</span>
      {item.estimated_minutes ? (
        <span className="shrink-0 text-2xs text-faint">{formatMinutes(item.estimated_minutes)}</span>
      ) : null}
    </span>
  );

  return (
    <li>
      {isContainer ? (
        <div
          style={indent}
          className={cn(
            "flex items-center gap-2 rounded px-2 py-1 text-2xs font-semibold uppercase tracking-wide",
            item.kind === "track" ? "text-muted" : "text-faint",
          )}
        >
          {inner}
        </div>
      ) : (
        <Link
          href={routes.workspace(subjectId, mode, item.id)}
          aria-current={active ? "page" : undefined}
          style={indent}
          className={cn(
            "flex items-center gap-2 rounded px-2 py-1 text-xs transition-colors",
            active ? "bg-accent/10 text-ink" : "text-muted hover:bg-raised hover:text-ink",
          )}
        >
          {inner}
        </Link>
      )}
      {children.length > 0 ? (
        <ul className="space-y-0.5">
          {children.map((child) => (
            <TreeRow key={child.item.id} node={child} subjectId={subjectId} mode={mode} activeId={activeId} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
