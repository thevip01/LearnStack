"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { routes } from "@/lib/routes";
import type { LearningMode, NavigationItem, SubjectRuntimeOut } from "@/lib/types";

/**
 * Navigation for panels.
 *
 * A panel that wants to move the learner (curriculum tree, next/prev links, the
 * command palette) pushes a route instead of calling into a sibling panel. The
 * URL is the shared state, so a deep link into a lesson is free.
 */
export function useWorkspaceNav(subjectId: string, mode: LearningMode) {
  const router = useRouter();

  const goToNode = useCallback(
    (nodeId: string) => router.push(routes.workspace(subjectId, mode, nodeId)),
    [mode, router, subjectId],
  );

  const goToMode = useCallback(
    (nextMode: LearningMode, nodeId: string | null) => router.push(routes.workspace(subjectId, nextMode, nodeId)),
    [router, subjectId],
  );

  return { goToNode, goToMode };
}

/** Reads the workspace coordinates out of the URL for client pages. */
export function useWorkspaceParams(): { subjectId: string; mode: string; nodeId: string | null } {
  const params = useParams<{ subjectId?: string; mode?: string }>();
  const search = useSearchParams();
  return {
    subjectId: params?.subjectId ?? "",
    mode: params?.mode ?? "",
    nodeId: search.get("node"),
  };
}

export type NavTreeNode = { item: NavigationItem; children: NavTreeNode[] };

/**
 * `navigation` arrives flattened, ordered and depth-tagged, so the tree is
 * rebuilt from `parent_id` in one pass. Items whose parent is missing are
 * attached at the root rather than dropped — a package with a dangling
 * `parent_id` should still be navigable.
 */
export function buildNavTree(items: NavigationItem[]): NavTreeNode[] {
  const nodes = new Map<string, NavTreeNode>();
  for (const item of items) nodes.set(item.id, { item, children: [] });

  const roots: NavTreeNode[] = [];
  for (const item of items) {
    const node = nodes.get(item.id);
    if (!node) continue;
    const parent = item.parent_id ? nodes.get(item.parent_id) : undefined;
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

/** First item a mode can sensibly open with: the first leaf, else the first item. */
export function firstSelectableNode(items: NavigationItem[]): NavigationItem | null {
  return items.find((item) => item.kind !== "track" && item.kind !== "module") ?? items[0] ?? null;
}

export function useNavItem(runtime: SubjectRuntimeOut, nodeId: string | null): NavigationItem | null {
  return useMemo(() => runtime.navigation.find((item) => item.id === nodeId) ?? null, [runtime.navigation, nodeId]);
}
