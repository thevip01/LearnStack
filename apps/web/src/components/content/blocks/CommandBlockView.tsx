"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import type { CommandBlock } from "@/lib/types";

const PROMPTS: Record<CommandBlock["shell"], string> = { bash: "$", powershell: "PS>", sql: "sql>" };

export function CommandBlockView({ block }: { block: CommandBlock }) {
  const [copied, setCopied] = useState(false);
  const prompt = PROMPTS[block.shell] ?? "$";

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(block.commands.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard denied; the commands remain selectable.
    }
  }

  return (
    <figure className="overflow-hidden rounded-panel border border-line bg-canvas">
      <div className="flex items-center justify-between border-b border-line bg-raised/60 px-2 py-1">
        <span className="font-mono text-2xs uppercase tracking-wide text-faint">{block.shell}</span>
        {block.copyable ? (
          <Button variant="ghost" size="xs" onClick={copyAll} aria-label="Copy all commands">
            {copied ? <Check className="size-3" aria-hidden /> : <Copy className="size-3" aria-hidden />}
            {copied ? "Copied" : "Copy"}
          </Button>
        ) : null}
      </div>
      <ol className="divide-y divide-line/60 font-mono text-[0.8125rem]">
        {block.commands.map((command, index) => (
          <li key={index} className="flex gap-2 px-2 py-1">
            <span aria-hidden className="select-none text-faint">
              {prompt}
            </span>
            <span className="whitespace-pre-wrap break-all text-ink/90">{command}</span>
          </li>
        ))}
      </ol>
      {block.caption ? (
        <figcaption className="border-t border-line px-2 py-1 text-2xs text-muted">{block.caption}</figcaption>
      ) : null}
    </figure>
  );
}
