import { Markdown } from "@/components/content/Markdown";
import { Badge } from "@/components/ui/Badge";
import type { TermBlock } from "@/lib/types";

export function TermBlockView({ block }: { block: TermBlock }) {
  return (
    <dl className="rounded-panel border border-line bg-raised/40 p-pad">
      <dt className="flex flex-wrap items-baseline gap-2">
        <span className="font-mono text-sm font-semibold text-accent">{block.term}</span>
        {block.aliases.map((alias) => (
          <Badge key={alias} tone="neutral">
            {alias}
          </Badge>
        ))}
      </dt>
      <dd className="mt-1.5">
        <Markdown>{block.definition_md}</Markdown>
      </dd>
    </dl>
  );
}
