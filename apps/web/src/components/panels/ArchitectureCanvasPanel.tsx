"use client";

import "@xyflow/react/dist/style.css";

import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Plus, RotateCcw, Send } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { Markdown } from "@/components/content/Markdown";
import { PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { SubmissionResult } from "@/components/practice/SubmissionResult";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { describeError } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { useActiveTask, useSubmitAttempt } from "@/lib/practice";
import { useWorkspaceStore } from "@/lib/store";
import type { ArchitectureNode, ArchitectureTaskOut } from "@/lib/types";

const NODE_STYLE = {
  background: "rgb(var(--os-raised))",
  color: "rgb(var(--os-ink))",
  border: "1px solid rgb(var(--os-line-strong))",
  borderRadius: 8,
  fontSize: 11,
  padding: "6px 10px",
  width: 168,
} as const;

/** An authored node → a ReactFlow node, laid out in a deterministic grid. */
function toFlowNode(node: ArchitectureNode, index: number): Node {
  return {
    id: node.id,
    position: { x: (index % 3) * 210, y: Math.floor(index / 3) * 104 },
    data: { label: node.label ?? node.type, componentType: node.type, config: node.config },
    style: NODE_STYLE,
  };
}

function toFlowEdge(pair: string[], index: number): Edge {
  return {
    id: `seed-${index}-${pair[0]}-${pair[1]}`,
    source: String(pair[0]),
    target: String(pair[1]),
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: "rgb(var(--os-line-strong))" },
  };
}

/**
 * The architecture design surface: an interactive graph the learner builds from a
 * fixed palette, then submits for grading.
 *
 * Nothing about the canvas knows what it is designing. The palette, the seed nodes
 * and the target properties all arrive on the task, so the same editor serves a
 * data pipeline, a web system or a deployment topology. Drag from a handle to
 * connect, click a palette chip to add a component, select and press Backspace to
 * remove. Submit maps the live graph straight back onto the wire shape
 * (`ArchitectureNode[]` + `[source, target]` edges); the grader owns the rubric.
 */
export function ArchitectureCanvasPanel({ runtime, mode, nodeId, panel }: PanelProps) {
  const { task, workspace, isLoading, error } = useActiveTask({
    runtime,
    mode,
    nodeId,
    panel,
    accept: ["architecture"],
  });

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const submit = useSubmitAttempt(task?.id ?? null, workspace);
  const result = useWorkspaceStore((state) => (task ? state.results[task.id] : undefined));

  // A monotonic id source for palette-added nodes, and a guard so we seed the
  // canvas from the task exactly once per task (never clobbering learner edits).
  const idRef = useRef(0);
  const seededRef = useRef<string | null>(null);

  const seed = useCallback(
    (architecture: ArchitectureTaskOut) => {
      const seeded = architecture.initial_nodes.map(toFlowNode);
      setNodes(seeded);
      setEdges(architecture.initial_edges.map(toFlowEdge));
      idRef.current = seeded.length;
    },
    [setNodes, setEdges],
  );

  useEffect(() => {
    if (!task || task.kind !== "architecture") return;
    if (seededRef.current === task.id) return;
    seededRef.current = task.id;
    seed(task);
  }, [task, seed]);

  const onConnect = useCallback(
    (connection: Connection) =>
      setEdges((current) => addEdge({ ...connection, markerEnd: { type: MarkerType.ArrowClosed } }, current)),
    [setEdges],
  );

  const addComponent = useCallback(
    (componentType: string) => {
      const id = `${componentType}-${idRef.current++}`;
      setNodes((current) => [
        ...current,
        {
          id,
          position: { x: 60 + (current.length % 4) * 40, y: 40 + current.length * 12 },
          data: { label: componentType, componentType, config: {} as Record<string, unknown> },
          style: NODE_STYLE,
        },
      ]);
    },
    [setNodes],
  );

  if (isLoading) return <PanelLoading label="Loading canvas" rows={8} />;
  if (error) return <PanelError error={error} />;
  if (!task) return <PanelHint title="No design task" description="Pick an architecture task to open the canvas." />;
  if (task.kind !== "architecture") {
    return <PanelHint title="Opens elsewhere" description="This task type is solved in its own panel." />;
  }

  // task is now narrowed to ArchitectureTaskOut.
  const onSubmit = () => {
    const payloadNodes: ArchitectureNode[] = nodes.map((node) => ({
      id: node.id,
      type: String(node.data.componentType ?? "component"),
      label: node.data.label != null ? String(node.data.label) : null,
      config: (node.data.config as Record<string, unknown>) ?? {},
    }));
    const payloadEdges = edges.map((edge) => [edge.source, edge.target] as [string, string]);
    void submit.mutateAsync({ kind: "architecture", nodes: payloadNodes, edges: payloadEdges }).catch(() => {});
  };

  return (
    <>
      <PanelToolbar className="flex-wrap gap-y-1.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
          <Plus className="size-3 text-faint" aria-hidden />
          {task.palette.map((component) => (
            <button
              key={component}
              type="button"
              onClick={() => addComponent(component)}
              className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-2xs text-muted transition-colors hover:border-line-strong hover:text-ink"
            >
              {component}
            </button>
          ))}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <Button size="xs" variant="ghost" onClick={() => seed(task)} title="Reset to the starting design">
            <RotateCcw className="size-3" aria-hidden />
            Reset
          </Button>
          <Button size="xs" variant="primary" onClick={onSubmit} loading={submit.isPending} disabled={submit.isPending}>
            <Send className="size-3" aria-hidden />
            Submit
          </Button>
        </div>
      </PanelToolbar>

      {task.target_properties.length > 0 ? (
        <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-line px-pad py-1.5">
          <span className="text-2xs text-faint">Design for:</span>
          {task.target_properties.map((property) => (
            <Badge key={property} tone="neutral">
              {titleCase(property)}
            </Badge>
          ))}
        </div>
      ) : null}

      {submit.error ? (
        <div className="shrink-0 border-b border-danger/30 bg-danger/5 px-pad py-1 text-2xs text-danger">
          {describeError(submit.error).message}
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
          proOptions={{ hideAttribution: false }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="rgb(var(--os-line))" />
          <Controls showInteractive={false} className="!bg-surface !text-ink" />
        </ReactFlow>
        {task.constraints_md.length > 0 ? (
          <aside className="pointer-events-none absolute right-2 top-2 max-w-[15rem] rounded-panel border border-line bg-surface/95 p-2 text-2xs shadow-lg">
            <div className="mb-1 font-semibold uppercase tracking-wide text-faint">Constraints</div>
            <ul className="space-y-1 text-muted">
              {task.constraints_md.map((constraint, index) => (
                <li key={index} className="leading-snug [&_*]:inline">
                  <Markdown>{constraint}</Markdown>
                </li>
              ))}
            </ul>
          </aside>
        ) : null}
      </div>

      {result ? (
        <div className="max-h-64 shrink-0 overflow-auto border-t border-line p-pad">
          <SubmissionResult result={result} subjectId={runtime.id} mode={mode} />
        </div>
      ) : null}
    </>
  );
}
