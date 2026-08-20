"use client";

import { Timer } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChoiceQuestion } from "@/components/practice/questions/ChoiceQuestion";
import { FillBlankQuestion } from "@/components/practice/questions/FillBlankQuestion";
import { MatchingQuestion } from "@/components/practice/questions/MatchingQuestion";
import { OrderingQuestion } from "@/components/practice/questions/OrderingQuestion";
import { QuestionFrame } from "@/components/practice/questions/QuestionFrame";
import { ShortAnswerQuestion } from "@/components/practice/questions/ShortAnswerQuestion";
import { SubmissionResult } from "@/components/practice/SubmissionResult";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PanelBody, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { useToast } from "@/components/ui/Toast";
import { formatDuration } from "@/lib/format";
import { useSubmitAttempt } from "@/lib/practice";
import { useWorkspaceStore } from "@/lib/store";
import type { LearningMode, QuizAnswerMap, QuizTaskOut, SafeQuestion } from "@/lib/types";

type Answer = QuizAnswerMap[string];

/** One input per question type. The six kinds in practice.py, no fallthrough. */
function QuestionInput({
  question,
  value,
  onChange,
  disabled,
}: {
  question: SafeQuestion;
  value: Answer | undefined;
  onChange: (next: Answer) => void;
  disabled: boolean;
}) {
  switch (question.type) {
    case "mcq":
    case "multi_select":
      return (
        <ChoiceQuestion
          question={question}
          value={value as string | string[] | undefined}
          onChange={onChange}
          disabled={disabled}
        />
      );
    case "fill_blank":
      return (
        <FillBlankQuestion question={question} value={value as string[] | undefined} onChange={onChange} disabled={disabled} />
      );
    case "ordering":
      return (
        <OrderingQuestion question={question} value={value as string[] | undefined} onChange={onChange} disabled={disabled} />
      );
    case "matching":
      return (
        <MatchingQuestion
          question={question}
          value={value as Record<string, string> | undefined}
          onChange={onChange}
          disabled={disabled}
        />
      );
    case "short_answer":
      return <ShortAnswerQuestion question={question} value={value as string | undefined} onChange={onChange} disabled={disabled} />;
  }
}

export type QuizOptions = {
  oneQuestionAtATime: boolean;
  showExplanations: boolean;
  allowRetry: boolean;
  showTimer: boolean;
  lockAfterAnswer: boolean;
};

/**
 * Runs a quiz task end to end.
 *
 * Question order is whatever the API served: `shuffle` is applied by the server
 * when it sanitises the task, so re-shuffling here would reorder the list under
 * the learner on every render.
 */
export function QuizRunner({
  task,
  workspace,
  subjectId,
  mode,
  options,
}: {
  task: QuizTaskOut;
  workspace: string;
  subjectId: string;
  mode: LearningMode;
  options: QuizOptions;
}) {
  const [answers, setAnswers] = useState<QuizAnswerMap>({});
  const [index, setIndex] = useState(0);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const stored = useWorkspaceStore((state) => state.results[task.id]);
  const submit = useSubmitAttempt(task.id, workspace);
  const toast = useToast();
  const formRef = useRef<HTMLDivElement>(null);

  const result = stored && stored.attempt_id !== dismissed ? stored : null;
  const graded = result !== null;
  const resultsById = useMemo(
    () => new Map((result?.question_results ?? []).map((entry) => [entry.question_id, entry])),
    [result],
  );

  const send = useCallback(async () => {
    if (graded || submit.isPending) return;
    try {
      await submit.mutateAsync({ kind: "quiz", answers });
    } catch (error) {
      toast.push({
        tone: "error",
        title: "Submission failed",
        message: error instanceof Error ? error.message : "the practice service rejected the submission",
      });
    }
  }, [answers, graded, submit, toast]);

  // Timed exams submit themselves. The countdown is display only; the API owns
  // the real clock via the attempt's started_at.
  const [remaining, setRemaining] = useState<number | null>(task.time_limit_s ?? null);
  useEffect(() => {
    if (!options.showTimer || task.time_limit_s === null || graded) return;
    const started = Date.now();
    const limit = task.time_limit_s;
    const handle = window.setInterval(() => {
      const left = Math.max(limit - Math.round((Date.now() - started) / 1000), 0);
      setRemaining(left);
      if (left === 0) void send();
    }, 1000);
    return () => window.clearInterval(handle);
  }, [graded, options.showTimer, send, task.time_limit_s]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        void send();
      }
    }
    const node = formRef.current;
    node?.addEventListener("keydown", onKeyDown);
    return () => node?.removeEventListener("keydown", onKeyDown);
  }, [send]);

  const visible = options.oneQuestionAtATime ? task.questions.slice(index, index + 1) : task.questions;
  const answeredCount = task.questions.filter((question) => answers[question.id] !== undefined).length;

  /** Exam-style layouts can freeze an answer as soon as it is given. */
  function isLocked(questionId: string): boolean {
    if (graded) return true;
    return options.lockAfterAnswer && answers[questionId] !== undefined;
  }

  function setAnswer(questionId: string, next: Answer) {
    setAnswers((current) => ({ ...current, [questionId]: next }));
  }

  function retry() {
    if (!result) return;
    setDismissed(result.attempt_id);
    setAnswers({});
    setIndex(0);
  }

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{task.title}</span>
        <Badge tone="neutral">{task.questions.length} questions</Badge>
        <Badge tone={answeredCount === task.questions.length ? "ok" : "neutral"}>
          {answeredCount} answered
        </Badge>
        {options.showTimer && remaining !== null ? (
          <Badge tone={remaining < 60 ? "warn" : "neutral"} glyph="⏱">
            {formatDuration(remaining * 1000)}
          </Badge>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">
          {options.oneQuestionAtATime ? (
            <>
              <Button size="xs" variant="ghost" disabled={index === 0} onClick={() => setIndex(index - 1)}>
                Previous
              </Button>
              <span className="font-mono text-2xs text-faint">
                {index + 1}/{task.questions.length}
              </span>
              <Button
                size="xs"
                variant="ghost"
                disabled={index >= task.questions.length - 1}
                onClick={() => setIndex(index + 1)}
              >
                Next
              </Button>
            </>
          ) : null}
          {graded && options.allowRetry ? (
            <Button size="xs" variant="outline" onClick={retry}>
              Try again
            </Button>
          ) : null}
          <Button size="xs" variant="primary" onClick={send} loading={submit.isPending} disabled={graded}>
            Submit <kbd className="ml-1">⌘↵</kbd>
          </Button>
        </div>
      </PanelToolbar>

      <PanelBody className="space-y-3 p-pad">
        <div ref={formRef} className="space-y-3">
          <ol className="space-y-3">
            {visible.map((question) => {
              const questionResult = resultsById.get(question.id);
              return (
                <QuestionFrame
                  key={question.id}
                  question={question}
                  index={task.questions.indexOf(question)}
                  result={options.showExplanations ? questionResult : undefined}
                >
                  <QuestionInput
                    question={question}
                    value={answers[question.id]}
                    onChange={(next) => setAnswer(question.id, next)}
                    disabled={isLocked(question.id)}
                  />
                </QuestionFrame>
              );
            })}
          </ol>
        </div>

        {options.showTimer && task.time_limit_s !== null && !graded ? (
          <p className="flex items-center gap-1.5 text-2xs text-faint">
            <Timer className="size-3" aria-hidden />
            The attempt submits itself when the timer reaches zero.
          </p>
        ) : null}

        {result ? (
          <SubmissionResult
            result={result}
            subjectId={subjectId}
            mode={mode}
            onRetry={options.allowRetry ? retry : undefined}
          />
        ) : null}
      </PanelBody>
    </>
  );
}
