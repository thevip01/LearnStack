import type { LearningMode } from "./types";

/**
 * Every internal URL is built here.
 *
 * The workspace URL is the only piece of application state that is not in the
 * store: `/subjects/{id}/{mode}?node={navItemId}` is shareable, back/forward
 * works, and a panel that wants to move the learner somewhere pushes a route
 * rather than reaching into another panel.
 */
export const routes = {
  home: "/",
  subjects: "/subjects",
  subject: (subjectId: string) => `/subjects/${encodeURIComponent(subjectId)}`,
  workspace: (subjectId: string, mode: LearningMode, nodeId?: string | null) => {
    const base = `/subjects/${encodeURIComponent(subjectId)}/${mode}`;
    return nodeId ? `${base}?node=${encodeURIComponent(nodeId)}` : base;
  },
  progress: (subjectId: string) => `/progress/${encodeURIComponent(subjectId)}`,
  search: (query?: string | null) => (query ? `/search?q=${encodeURIComponent(query)}` : "/search"),
  compare: (ids: string[]) => `/compare?ids=${encodeURIComponent(ids.join(","))}`,
  login: (next?: string | null) => (next ? `/login?next=${encodeURIComponent(next)}` : "/login"),
  adminIngestion: "/admin/ingestion",
};

/** Where a search hit or a recommendation should send the learner. */
export function targetRoute(
  subjectId: string,
  kind: string,
  id: string,
  mode: LearningMode | null = null,
): string {
  switch (kind) {
    case "practice":
      return routes.workspace(subjectId, mode ?? "practice", id);
    case "project":
      return routes.workspace(subjectId, mode ?? "project", id);
    case "assessment":
      return routes.workspace(subjectId, mode ?? "exam", id);
    case "review":
      return routes.workspace(subjectId, mode ?? "review", id);
    case "skill":
      return routes.progress(subjectId);
    case "subject":
      return routes.subject(id);
    default:
      return routes.workspace(subjectId, mode ?? "learn", id);
  }
}
