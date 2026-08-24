"use client";

import { CalloutBlockView } from "@/components/content/blocks/CalloutBlockView";
import { CommandBlockView } from "@/components/content/blocks/CommandBlockView";
import { DiagramBlockView } from "@/components/content/blocks/DiagramBlockView";
import { ProseBlockView } from "@/components/content/blocks/ProseBlockView";
import { RunnableCodeBlockView } from "@/components/content/blocks/RunnableCodeBlockView";
import { StepsBlockView } from "@/components/content/blocks/StepsBlockView";
import { TableBlockView } from "@/components/content/blocks/TableBlockView";
import { TermBlockView } from "@/components/content/blocks/TermBlockView";
import { EmbeddedPractice } from "@/components/practice/EmbeddedPractice";
import { workspaceKey } from "@/lib/store";
import type { ContentBlock, LearningMode } from "@/lib/types";

/**
 * Renders a `ContentBlock[]`: the one place the block union is dispatched.
 *
 * The switch is exhaustive by the discriminant, so a new block variant in the
 * schema surfaces as a TypeScript error here rather than a silently dropped
 * block in a lesson. The workspace key is threaded through so a runnable snippet
 * shares the same console the editor panels write to.
 */
export function ContentBlocks({
  blocks,
  subjectId,
  mode,
}: {
  blocks: ContentBlock[];
  subjectId: string;
  mode: LearningMode;
}) {
  const workspace = workspaceKey(subjectId, mode);
  return (
    <div className="space-y-4">
      {blocks.map((block, index) => (
        <BlockView key={index} block={block} workspace={workspace} subjectId={subjectId} mode={mode} />
      ))}
    </div>
  );
}

function BlockView({
  block,
  workspace,
  subjectId,
  mode,
}: {
  block: ContentBlock;
  workspace: string;
  subjectId: string;
  mode: LearningMode;
}) {
  switch (block.type) {
    case "prose":
      return <ProseBlockView block={block} />;
    case "code":
      return <RunnableCodeBlockView block={block} workspace={workspace} />;
    case "callout":
      return <CalloutBlockView block={block} />;
    case "diagram":
      return <DiagramBlockView block={block} />;
    case "table":
      return <TableBlockView block={block} />;
    case "steps":
      return <StepsBlockView block={block} />;
    case "command":
      return <CommandBlockView block={block} />;
    case "term":
      return <TermBlockView block={block} />;
    case "embed_practice":
      return <EmbeddedPractice practiceId={block.practice_id} subjectId={subjectId} mode={mode} />;
  }
}
