"use client";

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { ApiError, apiFetch, fetchReadiness } from "./api";
import type {
  AuthOut,
  CatalogOut,
  CompareOut,
  ConceptOut,
  ExtractionCandidate,
  GraphOut,
  HistoryOut,
  IngestionRun,
  PracticeSummary,
  ProvenanceTrailOut,
  ReadinessOut,
  ReadyOut,
  RecommendationsOut,
  ReviewDecision,
  SearchOut,
  SkillDetailOut,
  SourceSpec,
  SubjectProgressOut,
  SubjectRuntimeOut,
  UserOut,
} from "./types";

/** One place for cache keys so an invalidation cannot miss a reader. */
export const qk = {
  ready: ["ready"] as const,
  me: ["me"] as const,
  catalog: ["catalog"] as const,
  subject: (subjectId: string) => ["subject", subjectId] as const,
  concept: (subjectId: string, conceptId: string) => ["concept", subjectId, conceptId] as const,
  graph: (subjectId: string) => ["graph", subjectId] as const,
  readiness: (subjectId: string, skillId: string) => ["readiness", subjectId, skillId] as const,
  next: (subjectId: string, limit: number) => ["next", subjectId, limit] as const,
  progress: (subjectId: string) => ["progress", subjectId] as const,
  skill: (subjectId: string, skillId: string) => ["skill", subjectId, skillId] as const,
  history: (subjectId: string, days: number) => ["history", subjectId, days] as const,
  task: (taskId: string) => ["task", taskId] as const,
  queue: (subjectId: string, skillId: string | null, limit: number) => ["queue", subjectId, skillId, limit] as const,
  search: (query: string, subjectId: string | null, kind: string | null) =>
    ["search", query, subjectId, kind] as const,
  compare: (ids: string[]) => ["compare", ids.join(",")] as const,
  ingestionRuns: (subjectId: string | null) => ["admin", "runs", subjectId] as const,
  ingestionRun: (runId: string) => ["admin", "run", runId] as const,
  candidates: (subjectId: string | null, status: string | null, target: string | null) =>
    ["admin", "candidates", subjectId, status, target] as const,
  sources: (subjectId: string | null) => ["admin", "sources", subjectId] as const,
  provenance: (entityId: string) => ["admin", "provenance", entityId] as const,
};

const MINUTE = 60_000;

// ---------------------------------------------------------------------------
// Platform + auth
// ---------------------------------------------------------------------------

export function useReady(): UseQueryResult<ReadyOut> {
  return useQuery({
    queryKey: qk.ready,
    queryFn: () => fetchReadiness<ReadyOut>("/readyz"),
    staleTime: MINUTE,
    retry: false,
  });
}

/** Resolves to null when anonymous: the shell renders a sign-in affordance, not a wall. */
export function useMe(): UseQueryResult<UserOut | null> {
  return useQuery({
    queryKey: qk.me,
    queryFn: async () => {
      try {
        return await apiFetch<UserOut>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.isUnauthorized) return null;
        throw error;
      }
    },
    staleTime: 5 * MINUTE,
    retry: false,
  });
}

/**
 * Everything cached was an answer about somebody else, including the anonymous
 * somebody.
 *
 * Nothing in a query key names the account, so a session change makes every cached
 * entry wrong at once, in both directions: a visitor who browsed and then signed in
 * has a cache full of anonymous zeros and cached 401s, and the person who signs out
 * leaves their progress sitting in memory for whoever signs in next. Reported as
 * "even after login it show unauthorized": the login itself had worked, and the page
 * was rendering the refusal it had cached a moment earlier.
 *
 * The order is the whole trick. `setQueryData` first, because it writes into the
 * existing `me` query and therefore *notifies* everything already watching it: the
 * shell, and every gate that decides whether to render a console or a locked state.
 * Then `resetQueries` puts the rest back to pending, which drops what was cached for
 * the previous identity and refetches whatever is currently on screen under the new
 * one.
 *
 * `clear()` was the first attempt and it is a trap. It removes queries out from
 * under their observers without telling them, so a mounted view with no other reason
 * to re-render keeps painting the old session's data: signing out of the ingestion
 * console left the console on screen, tabs and all, next to a header that had already
 * flipped to "Sign in". `resetQueries` is the one that notifies. `me` is excluded from
 * it because it was just answered by the login response, and resetting it would throw
 * that away to ask a question we know the answer to.
 */
function adoptSession(client: ReturnType<typeof useQueryClient>, user: UserOut | null): void {
  client.setQueryData(qk.me, user);
  void client.resetQueries({ predicate: (query) => query.queryKey[0] !== qk.me[0] });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; password: string }) =>
      apiFetch<AuthOut>("/auth/login", { method: "POST", body: input }),
    onSuccess: (data) => adoptSession(client, data.user),
  });
}

export function useRegister() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; password: string; display_name?: string }) =>
      apiFetch<AuthOut>("/auth/register", { method: "POST", body: input }),
    onSuccess: (data) => adoptSession(client, data.user),
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => adoptSession(client, null),
  });
}

// ---------------------------------------------------------------------------
// Catalogue and runtime
// ---------------------------------------------------------------------------

export function useCatalog(): UseQueryResult<CatalogOut> {
  return useQuery({ queryKey: qk.catalog, queryFn: () => apiFetch<CatalogOut>("/catalog"), staleTime: MINUTE });
}

export function useSubjectRuntime(subjectId: string | null): UseQueryResult<SubjectRuntimeOut> {
  return useQuery({
    queryKey: qk.subject(subjectId ?? ""),
    queryFn: () => apiFetch<SubjectRuntimeOut>(`/subjects/${subjectId}`),
    enabled: Boolean(subjectId),
    staleTime: MINUTE,
  });
}

export function useConcept(subjectId: string | null, conceptId: string | null): UseQueryResult<ConceptOut> {
  return useQuery({
    queryKey: qk.concept(subjectId ?? "", conceptId ?? ""),
    queryFn: () => apiFetch<ConceptOut>(`/subjects/${subjectId}/concepts/${conceptId}`),
    enabled: Boolean(subjectId && conceptId),
    staleTime: MINUTE,
  });
}

export function useGraph(subjectId: string | null): UseQueryResult<GraphOut> {
  return useQuery({
    queryKey: qk.graph(subjectId ?? ""),
    queryFn: () => apiFetch<GraphOut>(`/subjects/${subjectId}/graph`),
    enabled: Boolean(subjectId),
    staleTime: 5 * MINUTE,
  });
}

export function useReadiness(subjectId: string | null, skillId: string | null): UseQueryResult<ReadinessOut> {
  return useQuery({
    queryKey: qk.readiness(subjectId ?? "", skillId ?? ""),
    queryFn: () => apiFetch<ReadinessOut>(`/subjects/${subjectId}/readiness`, { query: { skill_id: skillId } }),
    enabled: Boolean(subjectId && skillId),
  });
}

export function useRecommendations(subjectId: string | null, limit = 5): UseQueryResult<RecommendationsOut> {
  return useQuery({
    queryKey: qk.next(subjectId ?? "", limit),
    queryFn: () => apiFetch<RecommendationsOut>(`/subjects/${subjectId}/next`, { query: { limit } }),
    enabled: Boolean(subjectId),
  });
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

export function useProgress(subjectId: string | null): UseQueryResult<SubjectProgressOut> {
  return useQuery({
    queryKey: qk.progress(subjectId ?? ""),
    queryFn: () => apiFetch<SubjectProgressOut>(`/progress/${subjectId}`),
    enabled: Boolean(subjectId),
  });
}

export function useSkillDetail(subjectId: string | null, skillId: string | null): UseQueryResult<SkillDetailOut> {
  return useQuery({
    queryKey: qk.skill(subjectId ?? "", skillId ?? ""),
    queryFn: () => apiFetch<SkillDetailOut>(`/progress/${subjectId}/skills/${skillId}`),
    enabled: Boolean(subjectId && skillId),
  });
}

export function useHistory(subjectId: string | null, days = 30): UseQueryResult<HistoryOut> {
  return useQuery({
    queryKey: qk.history(subjectId ?? "", days),
    queryFn: () => apiFetch<HistoryOut>(`/progress/${subjectId}/history`, { query: { days } }),
    enabled: Boolean(subjectId),
  });
}

// ---------------------------------------------------------------------------
// Practice discovery, search, compare
// ---------------------------------------------------------------------------

export function usePracticeQueue(
  subjectId: string | null,
  skillId: string | null = null,
  limit = 10,
  enabled = true,
): UseQueryResult<{ tasks: PracticeSummary[] }> {
  return useQuery({
    queryKey: qk.queue(subjectId ?? "", skillId, limit),
    queryFn: () =>
      apiFetch<{ tasks: PracticeSummary[] }>("/practice/queue", {
        query: { subject_id: subjectId, skill_id: skillId, limit },
      }),
    enabled: enabled && Boolean(subjectId),
  });
}

export function useSearch(
  query: string,
  options: { subjectId?: string | null; kind?: string | null; limit?: number } = {},
): UseQueryResult<SearchOut> {
  const { subjectId = null, kind = null, limit = 20 } = options;
  return useQuery({
    queryKey: qk.search(query, subjectId, kind),
    queryFn: () => apiFetch<SearchOut>("/search", { query: { q: query, subject_id: subjectId, kind, limit } }),
    enabled: query.trim().length > 1,
    staleTime: 30_000,
  });
}

export function useCompare(ids: string[]): UseQueryResult<CompareOut> {
  return useQuery({
    queryKey: qk.compare(ids),
    queryFn: () => apiFetch<CompareOut>("/compare", { query: { ids: ids.join(",") } }),
    enabled: ids.length >= 2,
  });
}

// ---------------------------------------------------------------------------
// Admin / ingestion
// ---------------------------------------------------------------------------

export function useIngestionRuns(subjectId: string | null): UseQueryResult<{ runs: IngestionRun[] }> {
  return useQuery({
    queryKey: qk.ingestionRuns(subjectId),
    queryFn: () => apiFetch<{ runs: IngestionRun[] }>("/admin/ingestion/runs", { query: { subject_id: subjectId } }),
    // A run in flight advances through ten stages; poll rather than make the
    // admin reload to find out whether extract finished.
    refetchInterval: 8000,
  });
}

export function useIngestionSources(subjectId: string | null): UseQueryResult<{ sources: SourceSpec[] }> {
  return useQuery({
    queryKey: qk.sources(subjectId),
    queryFn: () => apiFetch<{ sources: SourceSpec[] }>("/admin/ingestion/sources", { query: { subject_id: subjectId } }),
  });
}

export function useCandidates(
  subjectId: string | null,
  status: string | null,
  target: string | null,
): UseQueryResult<{ candidates: ExtractionCandidate[] }> {
  return useQuery({
    queryKey: qk.candidates(subjectId, status, target),
    queryFn: () =>
      apiFetch<{ candidates: ExtractionCandidate[] }>("/admin/ingestion/candidates", {
        query: { subject_id: subjectId, status, target },
      }),
  });
}

export function useProvenance(entityId: string | null): UseQueryResult<ProvenanceTrailOut> {
  return useQuery({
    queryKey: qk.provenance(entityId ?? ""),
    queryFn: () => apiFetch<ProvenanceTrailOut>(`/admin/provenance/${entityId}`),
    enabled: Boolean(entityId),
  });
}

export function useStartIngestionRun(subjectId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { source_ids?: string[]; stages?: string[]; dry_run: boolean }) =>
      apiFetch<IngestionRun>("/admin/ingestion/runs", { method: "POST", body: { subject_id: subjectId, ...input } }),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.ingestionRuns(subjectId) }),
  });
}

export function useReviewCandidate() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; decision: ReviewDecision; notes?: string }) =>
      apiFetch<ExtractionCandidate>(`/admin/ingestion/candidates/${input.id}/review`, {
        method: "POST",
        body: { decision: input.decision, notes: input.notes },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin", "candidates"] }),
  });
}
