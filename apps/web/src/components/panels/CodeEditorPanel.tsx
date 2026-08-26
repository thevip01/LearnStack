"use client";

import Editor from "@monaco-editor/react";
import { Lock, Play, Send } from "lucide-react";
import { useEffect } from "react";
import { SignInToAct, useSessionGate } from "@/components/practice/SignInToAct";
import { SubmissionResult } from "@/components/practice/SubmissionResult";
import { PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Button } from "@/components/ui/Button";
import { describeError } from "@/lib/api";
import { useActiveTask, useRunner, useSubmitAttempt } from "@/lib/practice";
import { bufferFiles, useWorkspaceStore } from "@/lib/store";
import type { PracticeTaskOut, SourceFile } from "@/lib/types";
import { cn } from "@/lib/utils";

const MONACO_LANG: Record<string, string> = {
  py: "python",
  pyi: "python",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "typescript",
  json: "json",
  jsonc: "json",
  sql: "sql",
  md: "markdown",
  markdown: "markdown",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  sh: "shell",
  bash: "shell",
  yml: "yaml",
  yaml: "yaml",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  go: "go",
  rs: "rust",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  hpp: "cpp",
  rb: "ruby",
  php: "php",
  txt: "plaintext",
};

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

function languageForPath(path: string | null): string {
  if (!path) return "plaintext";
  const base = basename(path).toLowerCase();
  if (base === "dockerfile") return "dockerfile";
  const ext = base.includes(".") ? (base.split(".").pop() ?? "") : "";
  return MONACO_LANG[ext] ?? "plaintext";
}

/** The editable, non-hidden files handed to a code/debug task. */
function editableFiles(task: PracticeTaskOut): SourceFile[] {
  if (task.kind === "code" || task.kind === "debug") return task.starter_files.filter((file) => !file.hidden);
  return [];
}

/**
 * The code editor: Monaco over the store's per-task buffers, plus Run and Submit.
 *
 * It owns no test bodies and no answer key: Run posts the current files to the
 * sandbox and Submit hands them to the grader, which runs the hidden tests server
 * side. Because buffers live in the store keyed by task id, the file explorer, a
 * mode switch and this editor all read the same text, and the console and
 * test-results panels light up from whichever run happened last.
 */
export function CodeEditorPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, workspace, isLoading, error } = useActiveTask({
    runtime,
    mode,
    nodeId,
    panel,
    accept: ["code", "debug"],
  });

  const seedBuffers = useWorkspaceStore((state) => state.seedBuffers);
  const setBuffer = useWorkspaceStore((state) => state.setBuffer);
  const setActiveFile = useWorkspaceStore((state) => state.setActiveFile);
  const buffers = useWorkspaceStore((state) => (task ? state.buffers[task.id] : undefined));
  const storedActive = useWorkspaceStore((state) => (task ? state.activeFile[task.id] : undefined));
  const result = useWorkspaceStore((state) => (task ? state.results[task.id] : undefined));

  const { run, pending: running, error: runError } = useRunner(workspace);
  const submit = useSubmitAttempt(task?.id ?? null, workspace);
  const gate = useSessionGate();

  useEffect(() => {
    if (!task) return;
    const files = editableFiles(task);
    if (files.length > 0) seedBuffers(task.id, files.map((file) => ({ path: file.path, content: file.content })));
  }, [task, seedBuffers]);

  if (isLoading) return <PanelLoading label="Loading editor" rows={8} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No code task" description="Pick a coding task to open the editor." />;
  if (task.kind !== "code" && task.kind !== "debug") {
    return <PanelHint title="Opens elsewhere" description="This task type is solved in its own panel." />;
  }

  // task is now narrowed to CodeTaskOut | DebugTaskOut.
  const order = editableFiles(task);
  const currentPath = (storedActive && order.some((f) => f.path === storedActive) ? storedActive : order[0]?.path) ?? null;
  const currentFile = order.find((file) => file.path === currentPath) ?? null;
  const readOnly = currentFile?.readonly ?? false;
  const value = (currentPath != null ? buffers?.[currentPath] : undefined) ?? currentFile?.content ?? "";

  const collectFiles = () =>
    buffers ? bufferFiles(buffers, order) : order.map((file) => ({ path: file.path, content: file.content }));

  const onRun = () => {
    void run({ files: collectFiles(), command: task.run_command, limits: task.environment }).catch(() => {});
  };
  const onSubmit = () => {
    void submit.mutateAsync({ kind: task.kind, files: collectFiles() }).catch(() => {});
  };

  const actionError = runError ?? submit.error;

  return (
    <>
      <PanelToolbar className="gap-0">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {order.map((file) => {
            const active = file.path === currentPath;
            return (
              <button
                key={file.path}
                type="button"
                onClick={() => setActiveFile(task.id, file.path)}
                aria-current={active ? "true" : undefined}
                title={file.path}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1 rounded-t border-b-2 px-2 py-1 font-mono text-2xs transition-colors",
                  active
                    ? "border-accent text-ink"
                    : "border-transparent text-faint hover:text-ink",
                )}
              >
                {basename(file.path)}
                {file.readonly ? <Lock className="size-2.5" aria-hidden /> : null}
              </button>
            );
          })}
        </div>
        <div className="ml-2 flex shrink-0 items-center gap-1.5">
          {gate.locked ? null : (
            <Button size="xs" variant="secondary" onClick={onRun} loading={running} disabled={running}>
              <Play className="size-3" aria-hidden />
              Run
            </Button>
          )}
          {gate.locked ? (
            <SignInToAct action="submit this solution" />
          ) : (
            <Button size="xs" variant="primary" onClick={onSubmit} loading={submit.isPending} disabled={submit.isPending}>
              <Send className="size-3" aria-hidden />
              Submit
            </Button>
          )}
        </div>
      </PanelToolbar>

      {actionError ? (
        <div className="shrink-0 border-b border-danger/30 bg-danger/5 px-pad py-1 text-2xs text-danger">
          {describeError(actionError).message}
        </div>
      ) : null}

      <div className="min-h-0 flex-1">
        <Editor
          key={task.id}
          height="100%"
          theme="vs-dark"
          path={currentPath ?? "untitled"}
          language={languageForPath(currentPath)}
          value={value}
          onChange={(next) => {
            if (currentPath && !readOnly) setBuffer(task.id, currentPath, next ?? "");
          }}
          loading={<PanelLoading label="Loading editor" rows={6} />}
          options={{
            readOnly,
            domReadOnly: readOnly,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: "on",
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 4,
            insertSpaces: true,
            renderWhitespace: "selection",
            smoothScrolling: true,
            padding: { top: 10, bottom: 10 },
            scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
          }}
        />
      </div>

      {result ? (
        <div className="max-h-64 shrink-0 overflow-auto border-t border-line p-pad">
          <SubmissionResult result={result} subjectId={runtime.id} mode={mode} />
        </div>
      ) : null}
    </>
  );
}
