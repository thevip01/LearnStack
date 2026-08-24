"use client";

import { DiagramBlockView } from "@/components/content/blocks/DiagramBlockView";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { useNavItem } from "@/components/runtime/nav";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { useConcept } from "@/lib/queries";
import type { DiagramBlock } from "@/lib/types";
import { cfgString } from "@/lib/utils";

const FORMATS: ReadonlyArray<DiagramBlock["format"]> = ["mermaid", "ascii", "topology"];

function asFormat(value: string | null): DiagramBlock["format"] {
  return value && (FORMATS as readonly string[]).includes(value) ? (value as DiagramBlock["format"]) : "mermaid";
}

/**
 * A diagram surfaced on its own, rather than inline in the reading.
 *
 * Two ways a layout can feed it, in priority order: an explicit `config.source`
 * (with `config.format`) pins one diagram regardless of navigation; otherwise it
 * lifts every diagram block out of the concept named by the current nav node.
 * Either way the actual rendering is the same generic `DiagramBlockView` the
 * content panel uses. There is no diagram code special to any subject here.
 */
export function DiagramPanel({ runtime, nodeId, panel }: PanelProps) {
  const explicitSource = cfgString(panel.config, "source");
  const navItem = useNavItem(runtime, nodeId);
  const isConcept = navItem?.kind === "concept";
  // The concept fetch is skipped entirely when the layout pinned a source.
  const { data: concept, isLoading, error } = useConcept(
    runtime.id,
    !explicitSource && isConcept ? nodeId : null,
  );

  if (explicitSource) {
    const block: DiagramBlock = {
      type: "diagram",
      format: asFormat(cfgString(panel.config, "format")),
      source: explicitSource,
      caption: cfgString(panel.config, "caption"),
      interactive: true,
    };
    return (
      <PanelBody className="p-pad">
        <DiagramBlockView block={block} />
      </PanelBody>
    );
  }

  if (!nodeId || !navItem) {
    return <PanelHint title="Nothing selected" description="Pick a concept to see its diagrams." />;
  }
  if (!isConcept) {
    return <PanelHint title="No diagram here" description="Diagrams attach to concepts. Open one to see them." />;
  }
  if (isLoading) return <PanelLoading label="Loading diagram" rows={5} />;
  if (error) return <PanelError error={error} />;
  if (!concept) return <PanelHint title="Diagram unavailable" />;

  const diagrams = concept.body.filter((block): block is DiagramBlock => block.type === "diagram");
  if (diagrams.length === 0) {
    return (
      <PanelHint title={`"${concept.title}" has no diagram`} description="This concept explains itself in prose and code." />
    );
  }

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{concept.title}</span>
        <Badge tone="neutral">
          {diagrams.length} diagram{diagrams.length === 1 ? "" : "s"}
        </Badge>
      </PanelToolbar>
      <PanelBody className="space-y-3 p-pad">
        {diagrams.map((block, index) => (
          <DiagramBlockView key={`${block.format}-${index}`} block={block} />
        ))}
      </PanelBody>
    </>
  );
}
