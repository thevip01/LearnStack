"use client";

import "@xyflow/react/dist/style.css";

import { Background, BackgroundVariant, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { titleCase } from "@/lib/format";

type TopologyNode = { id: string; type?: string; label?: string; group?: string; config?: Record<string, unknown> };
type Topology = { nodes: TopologyNode[]; edges: Array<{ source: string; target: string; label?: string }> };

/**
 * `DiagramBlock.source` for a topology is "a topology JSON string". The schema
 * does not pin its shape, so parsing is defensive and both edge spellings
 * (`[["a","b"]]` and `[{source,target}]`) are accepted. A malformed topology
 * shows the raw source rather than an empty canvas.
 */
export function parseTopology(source: string): Topology | { error: string } {
  try {
    const raw = JSON.parse(source) as Record<string, unknown>;
    const nodesRaw = Array.isArray(raw.nodes) ? raw.nodes : [];
    const nodes: TopologyNode[] = nodesRaw
      .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
      .map((entry) => ({
        id: String(entry.id ?? ""),
        type: typeof entry.type === "string" ? entry.type : undefined,
        label: typeof entry.label === "string" ? entry.label : undefined,
        group: typeof entry.group === "string" ? entry.group : undefined,
        config: typeof entry.config === "object" && entry.config !== null ? (entry.config as Record<string, unknown>) : undefined,
      }))
      .filter((node) => node.id.length > 0);

    const edgesRaw = Array.isArray(raw.edges) ? raw.edges : [];
    const edges = edgesRaw
      .map((entry) => {
        if (Array.isArray(entry) && entry.length >= 2) return { source: String(entry[0]), target: String(entry[1]) };
        if (typeof entry === "object" && entry !== null) {
          const record = entry as Record<string, unknown>;
          if (record.source && record.target) {
            return {
              source: String(record.source),
              target: String(record.target),
              label: typeof record.label === "string" ? record.label : undefined,
            };
          }
        }
        return null;
      })
      .filter((edge): edge is { source: string; target: string; label?: string } => edge !== null);

    if (nodes.length === 0) return { error: "topology has no nodes" };
    return { nodes, edges };
  } catch (error) {
    return { error: error instanceof Error ? error.message : "unparseable topology JSON" };
  }
}

/** Deterministic column layout: grouped by `group`, falling back to component type. */
function layout(topology: Topology): { nodes: Node[]; edges: Edge[] } {
  const columns = new Map<string, TopologyNode[]>();
  for (const node of topology.nodes) {
    const key = node.group ?? node.type ?? "component";
    const bucket = columns.get(key) ?? [];
    bucket.push(node);
    columns.set(key, bucket);
  }

  const nodes: Node[] = [];
  let columnIndex = 0;
  for (const [group, members] of columns) {
    members.forEach((member, rowIndex) => {
      nodes.push({
        id: member.id,
        position: { x: columnIndex * 220, y: rowIndex * 96 },
        data: { label: member.label ?? member.id, group, componentType: member.type ?? "component", config: member.config },
        style: {
          background: "rgb(var(--os-raised))",
          color: "rgb(var(--os-ink))",
          border: "1px solid rgb(var(--os-line-strong))",
          borderRadius: 8,
          fontSize: 11,
          padding: "6px 10px",
          width: 170,
        },
      });
    });
    columnIndex += 1;
  }

  const edges: Edge[] = topology.edges.map((edge, index) => ({
    id: `${edge.source}-${edge.target}-${index}`,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: "rgb(var(--os-line-strong))" },
    labelStyle: { fill: "rgb(var(--os-muted))", fontSize: 10 },
  }));

  return { nodes, edges };
}

export function TopologyView({
  source,
  interactive = false,
  height = 320,
}: {
  source: string;
  interactive?: boolean;
  height?: number;
}) {
  const parsed = useMemo(() => parseTopology(source), [source]);
  const [selected, setSelected] = useState<Node | null>(null);

  if ("error" in parsed) {
    return (
      <EmptyState tone="error" title="Topology could not be read" description={parsed.error}>
        <pre className="max-h-40 overflow-auto rounded border border-line bg-canvas p-2 font-mono text-2xs text-muted">
          {source}
        </pre>
      </EmptyState>
    );
  }

  const { nodes, edges } = layout(parsed);

  return (
    <div>
      <div style={{ height }} className="overflow-hidden rounded-panel border border-line bg-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={interactive}
          proOptions={{ hideAttribution: false }}
          onNodeClick={interactive ? (_, node) => setSelected(node) : undefined}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="rgb(var(--os-line))" />
          <Controls showInteractive={false} className="!bg-surface !text-ink" />
        </ReactFlow>
      </div>
      {interactive && selected ? (
        <dl className="mt-2 rounded-panel border border-line bg-raised/40 p-pad text-xs">
          <div className="font-semibold text-ink">{String(selected.data.label)}</div>
          <div className="mt-1 text-2xs text-muted">
            {titleCase(String(selected.data.componentType ?? "component"))} · {String(selected.data.group ?? "")}
          </div>
          {selected.data.config ? (
            <pre className="mt-2 overflow-auto rounded border border-line bg-canvas p-2 font-mono text-2xs text-muted">
              {JSON.stringify(selected.data.config, null, 2)}
            </pre>
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}
