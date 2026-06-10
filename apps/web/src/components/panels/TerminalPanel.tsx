"use client";

import { Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
// xterm's stylesheet is imported statically, the way the other panels import theirs:
// a dynamic `import()` of a .css path is an expression, so TypeScript needs a module
// type for it and there is none. The xterm *code* is still loaded lazily below, which
// is the part worth deferring.
import "@xterm/xterm/css/xterm.css";
import { SubmissionResult } from "@/components/practice/SubmissionResult";
import { PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { describeError } from "@/lib/api";
import { useActiveTask, useRunner, useSubmitAttempt } from "@/lib/practice";
import { useWorkspaceStore } from "@/lib/store";
import type { TerminalTaskOut } from "@/lib/types";

const TERM_THEME = {
  background: "#0d1117",
  foreground: "#c9d1d9",
  cursor: "#58a6ff",
  selectionBackground: "#264f78",
} as const;

/**
 * A shell over the sandbox: type a command, it runs against the task's initial
 * filesystem and the output streams back into xterm.
 *
 * Runs are stateless: every command executes against a fresh copy of
 * `initial_filesystem`, so this is a REPL, not a persistent session. That is
 * deliberate: the grader replays the full command list server side against the
 * hidden `goal_checks`, so the source of truth for "did they solve it" is the
 * ordered transcript we submit, never client-side state. xterm is imported inside
 * the effect so it never evaluates during SSR.
 */
export function TerminalPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, workspace, isLoading, error } = useActiveTask({
    runtime,
    mode,
    nodeId,
    panel,
    accept: ["terminal"],
  });

  const result = useWorkspaceStore((state) => (task ? state.results[task.id] : undefined));
  const { run } = useRunner(workspace);
  const submit = useSubmitAttempt(task?.id ?? null, workspace);

  const [commands, setCommands] = useState<string[]>([]);
  const [running, setRunning] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  // Refs so the xterm keypress handler, wired once per task, always sees the
  // latest run fn / task without tearing the terminal down and back up.
  const taskRef = useRef<TerminalTaskOut | null>(null);
  const runRef = useRef(run);
  const busyRef = useRef(false);

  const ready = !!task && task.kind === "terminal";
  taskRef.current = ready ? (task as TerminalTaskOut) : null;
  runRef.current = run;

  // Reset the transcript when the task changes.
  useEffect(() => {
    setCommands([]);
  }, [task?.id]);

  useEffect(() => {
    if (!ready) return;
    let disposed = false;
    let term: import("@xterm/xterm").Terminal | null = null;
    let observer: ResizeObserver | null = null;

    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed || !containerRef.current) return;

      const fit = new FitAddon();
      term = new Terminal({
        convertEol: true,
        cursorBlink: true,
        fontSize: 12,
        fontFamily: "var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
        theme: TERM_THEME,
        scrollback: 2000,
      });
      term.loadAddon(fit);
      term.open(containerRef.current);
      fit.fit();

      let input = "";
      const prompt = () => term!.write("\r\n$ ");
      term.write("Sandbox ready. Commands run against a fresh copy of the workspace.");
      prompt();

      const execute = async (cmd: string) => {
        const active = taskRef.current;
        if (!active) return;
        const head = cmd.split(/\s+/)[0] ?? "";
        if (active.allowed_commands.length > 0 && !active.allowed_commands.includes(head)) {
          term!.write(`\r\n\x1b[33mcommand not allowed: ${head}\x1b[0m`);
          prompt();
          return;
        }
        busyRef.current = true;
        setRunning(true);
        try {
          const res = await runRef.current({
            files: active.initial_filesystem.map((file) => ({ path: file.path, content: file.content })),
            command: cmd,
            limits: active.environment,
          });
          if (res.stdout) term!.write(`\r\n${res.stdout}`);
          if (res.stderr) term!.write(`\r\n\x1b[31m${res.stderr}\x1b[0m`);
          setCommands((prev) => [...prev, cmd]);
        } catch (err) {
          term!.write(`\r\n\x1b[31m${describeError(err).message}\x1b[0m`);
        } finally {
          busyRef.current = false;
          setRunning(false);
          prompt();
        }
      };

      term.onData((data) => {
        if (busyRef.current) return;
        if (data === "\r") {
          const cmd = input.trim();
          input = "";
          if (cmd) void execute(cmd);
          else prompt();
          return;
        }
        if (data === "") {
          if (input.length > 0) {
            input = input.slice(0, -1);
            term!.write("\b \b");
          }
          return;
        }
        if (data === "") {
          input = "";
          term!.write("^C");
          prompt();
          return;
        }
        // Printable input (including multi-char paste); drop control chars.
        const printable = Array.from(data).filter((ch) => ch >= " ").join("");
        if (printable) {
          input += printable;
          term!.write(printable);
        }
      });

      observer = new ResizeObserver(() => {
        try {
          fit.fit();
        } catch {
          /* container detached mid-resize */
        }
      });
      observer.observe(containerRef.current);
    })();

    return () => {
      disposed = true;
      observer?.disconnect();
      term?.dispose();
    };
  }, [ready, task?.id]);

  if (isLoading) return <PanelLoading label="Loading terminal" rows={6} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No terminal task" description="Pick a terminal task to open the shell." />;
  if (task.kind !== "terminal") {
    return <PanelHint title="Opens elsewhere" description="This task type is solved in its own panel." />;
  }

  const onSubmit = () => {
    void submit.mutateAsync({ kind: "terminal", commands }).catch(() => {});
  };

  return (
    <>
      <PanelToolbar>
        <span className="text-2xs text-faint">
          {commands.length} command{commands.length === 1 ? "" : "s"} run
        </span>
        {running ? <Badge tone="info">running</Badge> : null}
        {task.allowed_commands.length > 0 ? (
          <span className="ml-2 hidden truncate font-mono text-2xs text-faint sm:inline" title={task.allowed_commands.join(" ")}>
            allowed: {task.allowed_commands.join(", ")}
          </span>
        ) : null}
        <Button
          size="xs"
          variant="primary"
          className="ml-auto"
          onClick={onSubmit}
          loading={submit.isPending}
          disabled={submit.isPending || commands.length === 0}
        >
          <Send className="size-3" aria-hidden />
          Submit
        </Button>
      </PanelToolbar>

      {submit.error ? (
        <div className="shrink-0 border-b border-danger/30 bg-danger/5 px-pad py-1 text-2xs text-danger">
          {describeError(submit.error).message}
        </div>
      ) : null}

      <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden bg-[#0d1117] p-2" />

      {result ? (
        <div className="max-h-64 shrink-0 overflow-auto border-t border-line p-pad">
          <SubmissionResult result={result} subjectId={runtime.id} mode={mode} />
        </div>
      ) : null}
    </>
  );
}
