import { Markdown } from "@/components/content/Markdown";
import type { StepsBlock } from "@/lib/types";

export function StepsBlockView({ block }: { block: StepsBlock }) {
  return (
    <div className="rounded-panel border border-line bg-surface p-pad">
      {block.title ? (
        <div className="mb-2 text-2xs font-semibold uppercase tracking-wide text-muted">{block.title}</div>
      ) : null}
      <ol className="space-y-2">
        {block.steps.map((step, index) => (
          <li key={index} className="grid grid-cols-[1.5rem_1fr] gap-2">
            <span
              aria-hidden
              className="mt-0.5 flex size-5 items-center justify-center rounded-full border border-accent/40 bg-accent/10 font-mono text-2xs text-accent"
            >
              {index + 1}
            </span>
            <Markdown>{step}</Markdown>
          </li>
        ))}
      </ol>
    </div>
  );
}
