import { Markdown } from "@/components/content/Markdown";
import { SourceChips } from "@/components/content/SourceChips";
import type { ProseBlock } from "@/lib/types";

export function ProseBlockView({ block }: { block: ProseBlock }) {
  return (
    <div>
      <Markdown>{block.md}</Markdown>
      <SourceChips sources={block.sources} />
    </div>
  );
}
