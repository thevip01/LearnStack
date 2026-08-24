"use client";

import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { HintLadder } from "@/components/practice/HintLadder";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { difficultyLabel } from "@/lib/format";
import { useActiveTask } from "@/lib/practice";

/**
 * The hint ladder for whatever practice task is active in this workspace.
 *
 * It carries no subject knowledge and holds no hint text: `HintLadder` requests
 * each rung from the API on demand and the store remembers what has been spent,
 * so the same ladder survives a mode switch. The dimension (which decides the
 * penalty) comes off the task's evaluation, never from a branch here.
 */
export function HintsPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, isLoading, error } = useActiveTask({ runtime, mode, nodeId, panel });

  if (isLoading) return <PanelLoading label="Loading hints" rows={3} />;
  if (error) return <PanelError error={error} />;
  if (!task) {
    return <PanelHint title="No task selected" description="Hints appear for the active practice task." />;
  }

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{task.title}</span>
        <Badge tone="neutral">{task.kind}</Badge>
        <span className="ml-auto text-2xs text-faint">{difficultyLabel(task.difficulty)}</span>
      </PanelToolbar>
      <PanelBody>
        <HintLadder taskId={task.id} hintCount={task.hint_count} dimension={task.evaluation.dimension} />
      </PanelBody>
    </>
  );
}
