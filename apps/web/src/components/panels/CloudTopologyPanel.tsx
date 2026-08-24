"use client";

import { TopologyView } from "@/components/content/TopologyView";
import { PanelBody, PanelError, PanelHint, PanelLoading, PanelToolbar } from "@/components/panels/shared/PanelShell";
import { useNavItem } from "@/components/runtime/nav";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { useConcept } from "@/lib/queries";
import type { DiagramBlock } from "@/lib/types";
import { cfgString } from "@/lib/utils";

/**
 * A read-only cloud/service topology. Source resolution mirrors the diagram panel:
 * an explicit `config.source` (topology JSON) wins; otherwise it renders the
 * topology-format diagram blocks of the current concept. The rendering is the
 * shared `TopologyView`, so there is no cloud-specific graph code here: a topology
 * is just data in a known shape.
 */
export function CloudTopologyPanel({ runtime, nodeId, panel }: PanelProps) {
  const explicitSource = cfgString(panel.config, "source");
  const navItem = useNavItem(runtime, nodeId);
  const isConcept = navItem?.kind === "concept";
  const { data: concept, isLoading, error } = useConcept(runtime.id, !explicitSource && isConcept ? nodeId : null);

  if (explicitSource) {
    return (
      <PanelBody className="p-pad">
        <TopologyView source={explicitSource} interactive height={440} />
      </PanelBody>
    );
  }

  if (!nodeId || !navItem) {
    return <PanelHint title="Nothing selected" description="Pick a concept to see its topology." />;
  }
  if (!isConcept) {
    return <PanelHint title="No topology here" description="Topologies attach to concepts or are pinned by the layout." />;
  }
  if (isLoading) return <PanelLoading label="Loading topology" rows={5} />;
  if (error) return <PanelError error={error} />;

  const topologies = (concept?.body ?? []).filter(
    (block): block is DiagramBlock => block.type === "diagram" && block.format === "topology",
  );
  if (topologies.length === 0) {
    return <PanelHint title="No topology" description="This concept has no topology diagram to render." />;
  }

  return (
    <>
      <PanelToolbar>
        <span className="truncate text-xs font-medium text-ink">{concept?.title}</span>
        <Badge tone="neutral">
          {topologies.length} view{topologies.length === 1 ? "" : "s"}
        </Badge>
      </PanelToolbar>
      <PanelBody className="space-y-3 p-pad">
        {topologies.map((block, index) => (
          <TopologyView key={index} source={block.source} interactive={block.interactive} height={400} />
        ))}
      </PanelBody>
    </>
  );
}
