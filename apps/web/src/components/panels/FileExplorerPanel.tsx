"use client";

import { FileCode, Lock } from "lucide-react";
import { useEffect } from "react";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { useActiveTask } from "@/lib/practice";
import { useWorkspaceStore } from "@/lib/store";
import type { PracticeTaskOut, SourceFile } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The editable file set for a file-bearing task; hidden files never surface. */
function taskFiles(task: PracticeTaskOut): SourceFile[] {
  if (task.kind === "code" || task.kind === "debug") return task.starter_files.filter((file) => !file.hidden);
  if (task.kind === "terminal") return task.initial_filesystem.filter((file) => !file.hidden);
  return [];
}

/**
 * The file tree for the active lab. Seeding is shared with the editor through the
 * store (keyed by task id), so opening the explorer, editing in the editor and
 * switching modes all read the same buffers. Selecting a file only moves the
 * cursor — the editor is the one that renders it.
 */
export function FileExplorerPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, isLoading, error } = useActiveTask({
    runtime,
    mode,
    nodeId,
    panel,
    accept: ["code", "debug", "terminal"],
  });

  const seedBuffers = useWorkspaceStore((state) => state.seedBuffers);
  const setActiveFile = useWorkspaceStore((state) => state.setActiveFile);
  const activeFile = useWorkspaceStore((state) => (task ? state.activeFile[task.id] : undefined));

  const files = task ? taskFiles(task) : [];

  useEffect(() => {
    if (task && files.length > 0) seedBuffers(task.id, files.map((file) => ({ path: file.path, content: file.content })));
  }, [task, files, seedBuffers]);

  if (isLoading) return <PanelLoading label="Loading files" rows={4} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No lab selected" description="File-based tasks show their tree here." />;
  if (files.length === 0) {
    return <PanelHint title="No files" description="This task does not hand you a starting file tree." />;
  }

  return (
    <>
      <PanelToolbar>
        <span className="text-2xs font-semibold uppercase tracking-wide text-faint">Files</span>
        <span className="ml-auto text-2xs text-faint">{files.length}</span>
      </PanelToolbar>
      <PanelBody className="p-2">
        <ul className="space-y-0.5">
          {files.map((file) => {
            const active = file.path === activeFile;
            return (
              <li key={file.path}>
                <button
                  type="button"
                  onClick={() => setActiveFile(task.id, file.path)}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors",
                    active ? "bg-accent/10 text-ink" : "text-muted hover:bg-raised hover:text-ink",
                  )}
                >
                  <FileCode className={cn("size-3.5 shrink-0", active ? "text-accent" : "text-faint")} aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-mono">{file.path}</span>
                  {file.readonly ? <Lock className="size-3 shrink-0 text-faint" aria-hidden /> : null}
                </button>
              </li>
            );
          })}
        </ul>
      </PanelBody>
    </>
  );
}
