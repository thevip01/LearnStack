"use client";

import { Markdown } from "@/components/content/Markdown";
import {
  PanelBody,
  PanelError,
  PanelHint,
  PanelLoading,
  PanelToolbar,
  SectionTitle,
} from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { difficultyLabel, formatMinutes } from "@/lib/format";
import { useActiveTask } from "@/lib/practice";

/**
 * The brief for the active task. Every practice kind carries `prompt_md`; the
 * kind-specific extras (a debug symptom, a code task's requirements, an
 * architecture task's constraints) are appended by narrowing the discriminated
 * union: the panel renders authored markdown and never composes instructions.
 */
export function InstructionsPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, isLoading, error } = useActiveTask({ runtime, mode, nodeId, panel });

  if (isLoading) return <PanelLoading label="Loading instructions" rows={6} />;
  if (error) return <PanelError error={error} />;
  if (!task) {
    return <PanelHint title="No task selected" description="Pick a task to see what it asks for." />;
  }

  const bullets = (items: string[]) => items.map((item) => `- ${item}`).join("\n");

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{task.title}</span>
        <Badge tone="neutral">{task.kind}</Badge>
        <span className="ml-auto inline-flex items-center gap-2 text-2xs text-faint">
          <span>{difficultyLabel(task.difficulty)}</span>
          <span>{formatMinutes(task.estimated_minutes)}</span>
        </span>
      </PanelToolbar>

      <PanelBody className="mx-auto max-w-2xl space-y-4 p-pad">
        {task.kind === "debug" ? (
          <section className="rounded-panel border border-warn/30 bg-warn/5 p-pad">
            <SectionTitle>Reported symptom</SectionTitle>
            <Markdown className="text-sm">{task.symptom_md}</Markdown>
          </section>
        ) : null}

        <Markdown>{task.prompt_md}</Markdown>

        {(task.kind === "code" || task.kind === "debug") && task.requirements_md.length > 0 ? (
          <section>
            <SectionTitle>Requirements</SectionTitle>
            <Markdown className="text-sm">{bullets(task.requirements_md)}</Markdown>
          </section>
        ) : null}

        {task.kind === "sql" ? (
          <p className="text-2xs text-faint">
            {task.ordered
              ? "Row order matters, so your result must match exactly."
              : "Row order does not matter; the grader compares as a set."}
          </p>
        ) : null}

        {task.kind === "terminal" ? (
          <section className="space-y-2">
            {task.allowed_commands.length > 0 ? (
              <div>
                <SectionTitle>Allowed commands</SectionTitle>
                <div className="flex flex-wrap gap-1.5">
                  {task.allowed_commands.map((command) => (
                    <code key={command} className="rounded bg-raised px-1.5 py-0.5 font-mono text-2xs text-ink">
                      {command}
                    </code>
                  ))}
                </div>
              </div>
            ) : null}
            <p className="text-2xs text-faint">
              {task.goal_checks.length} goal{task.goal_checks.length === 1 ? "" : "s"} will be checked when you submit.
            </p>
          </section>
        ) : null}

        {task.kind === "api" ? (
          <section className="space-y-2">
            <SectionTitle>Endpoint</SectionTitle>
            <code className="block break-all rounded bg-raised px-2 py-1 font-mono text-2xs text-ink">
              {task.base_url}
            </code>
            {task.requests_spec_md ? <Markdown className="text-sm">{task.requests_spec_md}</Markdown> : null}
          </section>
        ) : null}

        {task.kind === "architecture" ? (
          <section className="space-y-3">
            {task.constraints_md.length > 0 ? (
              <div>
                <SectionTitle>Constraints</SectionTitle>
                <Markdown className="text-sm">{bullets(task.constraints_md)}</Markdown>
              </div>
            ) : null}
            {task.target_properties.length > 0 ? (
              <div>
                <SectionTitle>Must satisfy</SectionTitle>
                <div className="flex flex-wrap gap-1.5">
                  {task.target_properties.map((property) => (
                    <Badge key={property} tone="info">
                      {property}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {task.kind === "incident" ? (
          <section className="space-y-3">
            <div>
              <SectionTitle>Scenario</SectionTitle>
              <Markdown className="text-sm">{task.scenario_md}</Markdown>
            </div>
            {task.architecture_md ? (
              <div>
                <SectionTitle>Architecture</SectionTitle>
                <Markdown className="text-sm">{task.architecture_md}</Markdown>
              </div>
            ) : null}
            {task.symptoms.length > 0 ? (
              <div>
                <SectionTitle>Symptoms</SectionTitle>
                <Markdown className="text-sm">{bullets(task.symptoms)}</Markdown>
              </div>
            ) : null}
          </section>
        ) : null}
      </PanelBody>
    </>
  );
}
