import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { WorkspaceView } from "@/components/subject/WorkspaceView";
import { LEARNING_MODES, type LearningMode } from "@/lib/types";

export const metadata: Metadata = { title: "Workspace" };

function isLearningMode(value: string): value is LearningMode {
  return (LEARNING_MODES as readonly string[]).includes(value);
}

/**
 * `/subjects/{id}/{mode}?node={navItemId}`: the whole workspace address.
 *
 * The mode segment is validated against the vocabulary here so a typo 404s
 * instead of reaching the runtime as an unknown key, and the node selection is
 * read on the server and handed down as a prop, which keeps `useSearchParams`
 * (and its Suspense requirement) out of the runtime tree.
 */
export default async function WorkspacePage({
  params,
  searchParams,
}: {
  params: Promise<{ subjectId: string; mode: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ subjectId, mode }, query] = await Promise.all([params, searchParams]);
  if (!isLearningMode(mode)) notFound();

  const raw = query.node;
  const nodeId = Array.isArray(raw) ? raw[0] ?? null : raw ?? null;

  return <WorkspaceView subjectId={decodeURIComponent(subjectId)} mode={mode} nodeId={nodeId} />;
}
