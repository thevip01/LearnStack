"use client";

import { Mermaid } from "@/components/content/Mermaid";
import { TopologyView } from "@/components/content/TopologyView";
import type { DiagramBlock } from "@/lib/types";

export function DiagramBlockView({ block }: { block: DiagramBlock }) {
  return (
    <figure className="overflow-hidden rounded-panel border border-line bg-surface">
      <div className="p-pad">
        {block.format === "mermaid" ? <Mermaid source={block.source} /> : null}
        {block.format === "ascii" ? (
          <pre className="overflow-x-auto font-mono text-[0.8125rem] leading-5 text-ink/90">{block.source}</pre>
        ) : null}
        {block.format === "topology" ? (
          <TopologyView source={block.source} interactive={block.interactive} height={280} />
        ) : null}
      </div>
      {block.caption ? (
        <figcaption className="border-t border-line px-2 py-1 text-2xs text-muted">{block.caption}</figcaption>
      ) : null}
    </figure>
  );
}
