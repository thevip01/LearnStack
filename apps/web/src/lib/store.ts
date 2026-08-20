"use client";

import { create } from "zustand";
import type { AttemptOut, ExecutionResult, HintOut, LearningMode, Slot, SubmissionResultOut } from "./types";

/**
 * One store for everything that must outlive a panel.
 *
 * Switching mode swaps the entire layout, so the editor panel unmounts. If
 * buffers lived in component state a learner would lose their work every time
 * they glanced at the diagram in `learn` mode. They live here instead, keyed by
 * task id, and that same indirection is how `test_results` and `console` render
 * the outcome of a run started by a different panel.
 */

export type HttpExchange = {
  id: string;
  method: string;
  url: string;
  requestHeaders: Record<string, string>;
  requestBody: string | null;
  status: number | null;
  statusText: string;
  responseHeaders: Record<string, string>;
  responseBody: string;
  durationMs: number;
  error: string | null;
  at: string;
};

export function workspaceKey(subjectId: string | null, mode: LearningMode | null): string {
  return `${subjectId ?? "-"}:${mode ?? "-"}`;
}

export function slotKey(subjectId: string | null, mode: LearningMode | null, slot: Slot): string {
  return `${workspaceKey(subjectId, mode)}:${slot}`;
}

type EditorBuffers = Record<string, string>;

type WorkspaceState = {
  subjectId: string | null;
  mode: LearningMode | null;
  nodeId: string | null;
  setContext: (context: { subjectId: string; mode: LearningMode; nodeId: string | null }) => void;

  collapsed: Record<string, boolean>;
  setCollapsed: (key: string, value: boolean) => void;
  toggleCollapsed: (key: string) => void;

  activeTab: Record<string, string>;
  setActiveTab: (key: string, panelId: string) => void;

  sizes: Record<string, number>;
  setSize: (key: string, px: number) => void;

  activeTaskId: Record<string, string | null>;
  setActiveTask: (workspace: string, taskId: string | null) => void;

  buffers: Record<string, EditorBuffers>;
  activeFile: Record<string, string>;
  seedBuffers: (taskId: string, files: Array<{ path: string; content: string }>) => void;
  resetBuffers: (taskId: string, files: Array<{ path: string; content: string }>) => void;
  setBuffer: (taskId: string, path: string, content: string) => void;
  setActiveFile: (taskId: string, path: string) => void;

  attempts: Record<string, AttemptOut>;
  setAttempt: (taskId: string, attempt: AttemptOut) => void;

  hints: Record<string, HintOut[]>;
  addHint: (taskId: string, hint: HintOut) => void;

  results: Record<string, SubmissionResultOut>;
  setResult: (taskId: string, result: SubmissionResultOut) => void;

  runs: Record<string, ExecutionResult>;
  runPending: Record<string, boolean>;
  setRun: (workspace: string, result: ExecutionResult) => void;
  setRunPending: (workspace: string, pending: boolean) => void;

  httpLog: HttpExchange[];
  pushHttpExchange: (exchange: HttpExchange) => void;

  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
};

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  subjectId: null,
  mode: null,
  nodeId: null,
  setContext: ({ subjectId, mode, nodeId }) => set({ subjectId, mode, nodeId }),

  collapsed: {},
  setCollapsed: (key, value) => set((state) => ({ collapsed: { ...state.collapsed, [key]: value } })),
  toggleCollapsed: (key) => set((state) => ({ collapsed: { ...state.collapsed, [key]: !state.collapsed[key] } })),

  activeTab: {},
  setActiveTab: (key, panelId) => set((state) => ({ activeTab: { ...state.activeTab, [key]: panelId } })),

  sizes: {},
  setSize: (key, px) => set((state) => ({ sizes: { ...state.sizes, [key]: px } })),

  activeTaskId: {},
  setActiveTask: (workspace, taskId) =>
    set((state) => ({ activeTaskId: { ...state.activeTaskId, [workspace]: taskId } })),

  buffers: {},
  activeFile: {},
  // Seeding is idempotent on purpose: re-entering a task must not overwrite edits.
  seedBuffers: (taskId, files) =>
    set((state) => {
      if (state.buffers[taskId]) return state;
      const next: EditorBuffers = {};
      for (const file of files) next[file.path] = file.content;
      const first = files[0]?.path;
      return {
        buffers: { ...state.buffers, [taskId]: next },
        activeFile: first ? { ...state.activeFile, [taskId]: first } : state.activeFile,
      };
    }),
  resetBuffers: (taskId, files) =>
    set((state) => {
      const next: EditorBuffers = {};
      for (const file of files) next[file.path] = file.content;
      return { buffers: { ...state.buffers, [taskId]: next } };
    }),
  setBuffer: (taskId, path, content) =>
    set((state) => ({
      buffers: { ...state.buffers, [taskId]: { ...(state.buffers[taskId] ?? {}), [path]: content } },
    })),
  setActiveFile: (taskId, path) => set((state) => ({ activeFile: { ...state.activeFile, [taskId]: path } })),

  attempts: {},
  setAttempt: (taskId, attempt) => set((state) => ({ attempts: { ...state.attempts, [taskId]: attempt } })),

  hints: {},
  addHint: (taskId, hint) =>
    set((state) => {
      const existing = state.hints[taskId] ?? [];
      if (existing.some((entry) => entry.level === hint.level)) return state;
      return { hints: { ...state.hints, [taskId]: [...existing, hint].sort((a, b) => a.level - b.level) } };
    }),

  results: {},
  setResult: (taskId, result) => set((state) => ({ results: { ...state.results, [taskId]: result } })),

  runs: {},
  runPending: {},
  setRun: (workspace, result) => set((state) => ({ runs: { ...state.runs, [workspace]: result } })),
  setRunPending: (workspace, pending) =>
    set((state) => ({ runPending: { ...state.runPending, [workspace]: pending } })),

  httpLog: [],
  // Newest first, capped: the inspector only ever shows a working set.
  pushHttpExchange: (exchange) => set((state) => ({ httpLog: [exchange, ...state.httpLog].slice(0, 25) })),

  paletteOpen: false,
  setPaletteOpen: (open) => set({ paletteOpen: open }),
}));

/** Buffers for a task as an array in the order the API declared the files. */
export function bufferFiles(
  buffers: EditorBuffers | undefined,
  order: Array<{ path: string }>,
): Array<{ path: string; content: string }> {
  if (!buffers) return [];
  const known = order.map((file) => file.path).filter((path) => path in buffers);
  const extra = Object.keys(buffers).filter((path) => !known.includes(path));
  return [...known, ...extra].map((path) => ({ path, content: buffers[path] ?? "" }));
}
