"use client";

import { CheckSquare, Clock, Square, Target } from "lucide-react";
import { useState } from "react";
import { Markdown } from "@/components/content/Markdown";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar, SectionTitle } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { formatMinutes } from "@/lib/format";
import { useActiveTask } from "@/lib/practice";
import { cn } from "@/lib/utils";

/**
 * The capstone brief. It resolves the same task the project editor is bound to
 * (per-workspace task selection is shared), so the brief and the code the learner
 * writes never drift apart. The narrative lives in the task's `prompt_md` and the
 * acceptance criteria in `requirements_md`; `config.milestone_checklist` turns the
 * requirements into a scratch checklist so a learner can track their own progress
 * against them. The checklist is deliberately local and unsubmitted: the tests
 * are the real acceptance gate, not these boxes.
 */
export function ProjectBriefPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, isLoading, error } = useActiveTask({ runtime, mode, nodeId, panel, accept: ["code", "debug"] });
  const asChecklist = panel.config.milestone_checklist === true;
  const [checked, setChecked] = useState<Set<number>>(new Set());

  if (isLoading) return <PanelLoading label="Loading brief" rows={8} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No project" description="Pick a project to see its brief." />;

  const requirements = task.kind === "code" || task.kind === "debug" ? task.requirements_md : [];
  const toggle = (index: number) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{task.title}</span>
        <Badge tone="accent" glyph="◆">
          level {task.difficulty}
        </Badge>
        <span className="ml-auto inline-flex items-center gap-1 text-2xs text-faint">
          <Clock className="size-3" aria-hidden />
          {formatMinutes(task.estimated_minutes)}
        </span>
      </PanelToolbar>

      <PanelBody className="mx-auto max-w-2xl space-y-4 p-pad">
        <Markdown>{task.prompt_md}</Markdown>

        {requirements.length > 0 ? (
          <section className="space-y-1.5">
            <SectionTitle>
              <span className="inline-flex items-center gap-1.5">
                <Target className="size-3.5 text-accent" aria-hidden />
                {asChecklist ? `Requirements: ${checked.size}/${requirements.length}` : "Requirements"}
              </span>
            </SectionTitle>
            <ul className="space-y-1">
              {requirements.map((requirement, index) => {
                const isChecked = checked.has(index);
                return (
                  <li key={index} className="flex items-start gap-2">
                    {asChecklist ? (
                      <button
                        type="button"
                        onClick={() => toggle(index)}
                        aria-pressed={isChecked}
                        className="mt-0.5 shrink-0 text-muted transition-colors hover:text-ink"
                      >
                        {isChecked ? (
                          <CheckSquare className="size-4 text-ok" aria-hidden />
                        ) : (
                          <Square className="size-4" aria-hidden />
                        )}
                      </button>
                    ) : (
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
                    )}
                    <div className={cn("min-w-0 flex-1 text-sm leading-snug", isChecked && "text-faint line-through")}>
                      <Markdown>{requirement}</Markdown>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
      </PanelBody>
    </>
  );
}
