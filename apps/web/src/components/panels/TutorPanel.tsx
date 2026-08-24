"use client";

import { GraduationCap, Send } from "lucide-react";
import { NotWired } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { cfgStringArray } from "@/lib/utils";

const CONTEXT_LABEL: Record<string, string> = {
  current_concept: "the concept you're reading",
  current_task: "the task you're attempting",
  recent_failures: "your recent wrong answers",
};

/**
 * The tutor. Its answers come from an LLM service that is not part of this phase,
 * so rather than ship a chat box whose Send button does nothing, this renders an
 * honest "not connected" state that still describes, from the panel's own config,
 * exactly what the tutor will ground its answers in and the guardrails it will
 * respect. When the backend route lands, this panel becomes the chat surface.
 */
export function TutorPanel({ panel }: PanelProps) {
  const context = cfgStringArray(panel.config, "context");
  const citeSources = panel.config.cite_sources === true;
  const refuseGraded = panel.config.refuse_to_answer_graded_questions === true;

  const shape = [
    context.length > 0
      ? `Grounds every answer in ${context.map((key) => CONTEXT_LABEL[key] ?? key).join(", ")}`
      : "Answers questions about the current material",
    citeSources ? "Cites the source behind each claim, like the reading does" : null,
    refuseGraded ? "Declines questions that belong to a graded attempt" : null,
    "Streams replies into a conversation you can scroll back through",
  ].filter((line): line is string => Boolean(line));

  return (
    <NotWired
      title="Tutor isn't connected in this build"
      description="The tutor is powered by a language-model service that lands in a later phase. Its behavior is already pinned by this panel's configuration."
      shape={shape}
      icon={<GraduationCap className="size-5" aria-hidden />}
    >
      <div className="mt-3 flex items-center gap-1.5 opacity-60">
        <div className="flex h-8 flex-1 items-center rounded-md border border-line bg-canvas px-2.5 text-2xs text-faint">
          Ask about this concept…
        </div>
        <div className="grid size-8 shrink-0 place-items-center rounded-md border border-line bg-raised text-faint">
          <Send className="size-3.5" aria-hidden />
        </div>
      </div>
    </NotWired>
  );
}
