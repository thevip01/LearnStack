import { InlineMarkdown } from "@/components/content/Markdown";
import type { TableBlock } from "@/lib/types";

export function TableBlockView({ block }: { block: TableBlock }) {
  return (
    <figure className="overflow-hidden rounded-panel border border-line">
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="bg-raised">
              {block.columns.map((column) => (
                <th key={column} scope="col" className="border-b border-line px-2 py-1.5 font-semibold text-muted">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="odd:bg-surface even:bg-raised/40">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="border-b border-line/60 px-2 py-1.5 align-top text-ink/90">
                    <InlineMarkdown>{cell}</InlineMarkdown>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.caption ? (
        <figcaption className="border-t border-line bg-surface px-2 py-1 text-2xs text-muted">
          {block.caption}
        </figcaption>
      ) : null}
    </figure>
  );
}
