"use client";

import { PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { QuizRunner, type QuizOptions } from "@/components/practice/QuizRunner";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { useActiveTask } from "@/lib/practice";
import { workspaceKey } from "@/lib/store";
import { cfgBool } from "@/lib/utils";

/**
 * Hosts a quiz task. Task resolution (pinned by config, chosen by the learner,
 * or the first quiz for the current concept) lives in `useActiveTask`; this
 * panel only maps mode + config to the runner's display options.
 */
export function QuizPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, isLoading, error, candidates, select, taskId } = useActiveTask({
    runtime,
    mode,
    nodeId,
    panel,
    accept: ["quiz"],
  });

  const isExam = mode === "exam";
  const options: QuizOptions = {
    oneQuestionAtATime: cfgBool(panel.config, "one_question_at_a_time", isExam),
    showExplanations: cfgBool(panel.config, "show_explanations", !isExam),
    allowRetry: cfgBool(panel.config, "allow_retry", !isExam),
    showTimer: cfgBool(panel.config, "show_timer", isExam),
    lockAfterAnswer: cfgBool(panel.config, "lock_after_answer", isExam),
  };

  if (isLoading) return <PanelLoading label="Loading quiz" rows={5} />;
  if (error) return <PanelError error={error} />;
  if (!task) {
    return <PanelHint title="No quiz here" description="This concept has no quiz. Pick another node or mode." />;
  }
  if (task.kind !== "quiz") {
    return <PanelHint title="Not a quiz" description={`The selected task is a ${task.kind} task.`} />;
  }

  const quizzes = candidates.filter((candidate) => candidate.kind === "quiz");

  return (
    <>
      {quizzes.length > 1 ? (
        <PanelToolbar>
          <span className="text-2xs text-faint">Quiz:</span>
          {quizzes.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              onClick={() => select(candidate)}
              className="rounded"
              aria-current={candidate.id === taskId ? "true" : undefined}
            >
              <Badge tone={candidate.id === taskId ? "accent" : "neutral"}>{candidate.title}</Badge>
            </button>
          ))}
        </PanelToolbar>
      ) : null}
      <QuizRunner
        task={task}
        workspace={workspaceKey(runtime.id, mode)}
        subjectId={runtime.id}
        mode={mode}
        options={options}
      />
    </>
  );
}
