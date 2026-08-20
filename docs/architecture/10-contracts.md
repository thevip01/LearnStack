# Contracts

Everything in this file is binding. The API implements it, the web app consumes
it, and the ingestion service produces content that satisfies it. If a change is
needed, change this document in the same commit.

The Python models in `packages/knowledge-schema/learnos_schema/` are the
authoritative definition of content shapes. This document defines the **HTTP
surface** and the **response envelopes** that wrap those shapes.

---

## Conventions

- Base path `/api/v1`. Everything JSON, UTF-8.
- Ids are dotted lowercase strings (`programming.python`, `python.functions`,
  `practice.python.functions.code.1`). They appear in URLs unescaped.
- Timestamps are ISO 8601 with a `Z` offset.
- Scores are floats in `[0, 1]`. The UI multiplies by 100 for display; the API
  never sends percentages.
- Errors use a single envelope:

```json
{ "error": { "code": "not_found", "message": "unknown concept 'python.foo'", "detail": null } }
```

  Codes in use: `bad_request`, `unauthorized`, `forbidden`, `not_found`,
  `conflict`, `unprocessable`, `rate_limited`, `sandbox_unavailable`,
  `internal_error`.

- Auth is a bearer JWT **or** the `learnos_session` httpOnly cookie. Login and
  register set the cookie and also return the token in the body, so the browser
  uses cookies and scripts use the header. Cookie is `SameSite=Lax`,
  `Secure` when `ENV != "development"`.
- Endpoints marked *(auth optional)* work anonymously but omit the `progress`
  block. This keeps the subject catalogue and lesson content publicly renderable
  without a signup wall.

---

## Health

```
GET /healthz   -> 200 {"status":"ok","version":"0.1.0"}
GET /readyz    -> 200 {"status":"ready","postgres":true,"redis":true,"sandbox":"docker"}
               -> 503 when a dependency is down
```

`readyz.sandbox` is one of `docker`, `subprocess`, `unavailable`. The web app
surfaces a banner when it is not `docker`, because subprocess mode is a
development fallback with weaker isolation.

---

## Auth

```
POST /api/v1/auth/register   {email, password, display_name?}  -> 201 AuthOut
POST /api/v1/auth/login      {email, password}                  -> 200 AuthOut
POST /api/v1/auth/logout                                        -> 204
GET  /api/v1/auth/me                                            -> 200 UserOut
```

```ts
type AuthOut = { access_token: string; token_type: "bearer"; expires_in: number; user: UserOut }
type UserOut = { id: string; email: string; display_name: string; created_at: string; is_admin: boolean }
```

Passwords: bcrypt, minimum 10 characters. Registration is rate limited.

---

## Catalog and subject runtime

```
GET /api/v1/catalog                      (auth optional)  -> CatalogOut
GET /api/v1/subjects/{subject_id}        (auth optional)  -> SubjectRuntimeOut
```

`SubjectRuntimeOut` is the single payload that turns the generic frontend into
this subject. One request, everything the shell needs to draw itself.

```ts
type CatalogOut = {
  domains: Array<{
    id: string; title: string; icon: string | null
    subjects: Array<{
      id: string; title: string; subtitle: string | null; description: string
      provider: string | null; version: string; status: string
      theme: ThemeSpec; tags: string[]
      concept_count: number; practice_count: number; project_count: number
      estimated_minutes: number
      progress: { overall: number; skills_mastered: number; skills_total: number } | null
    }>
  }>
}

type SubjectRuntimeOut = {
  id: string; title: string; subtitle: string | null; description: string
  domain: { id: string; title: string; icon: string | null }
  provider: string | null
  version: string; content_hash: string; status: string
  theme: ThemeSpec
  layout: "learning_lab" | "ml_workbench" | "trading_desk" | "reader" | "canvas"
  default_mode: LearningMode
  modes: LearningMode[]
  mode_layouts: Record<LearningMode, ModeLayout>   // already merged with global_panels
  navigation: NavigationItem[]                     // flattened, ordered, depth-tagged
  tracks: Track[]                                  // for grouping headers, no concept bodies
  skills: Skill[]
  runtimes: RuntimeSpec[]
  progress: SubjectProgressOut | null
}
```

`mode_layouts` is pre-merged: the frontend renders `mode_layouts[mode].panels`
directly and never has to know about `global_panels`.

### Concepts

```
GET /api/v1/subjects/{subject_id}/concepts/{concept_id}   (auth optional) -> ConceptOut
```

```ts
type ConceptOut = Concept & {
  practice: PracticeSummary[]
  prerequisite_status: Array<{ concept_id: string; title: string; mastery: number | null; ready: boolean }>
  next_concept_id: string | null
  prev_concept_id: string | null
  module: { id: string; title: string; track_id: string; track_title: string } | null
}

type PracticeSummary = {
  id: string; kind: PracticeKind; title: string; difficulty: number
  estimated_minutes: number; hint_count: number
  skills: string[]
  state: "untouched" | "in_progress" | "passed" | "failed"
  best_score: number | null; attempts: number
}
```

### Graph, readiness, recommendations

```
GET /api/v1/subjects/{subject_id}/graph                        -> GraphOut
GET /api/v1/subjects/{subject_id}/readiness?skill_id=...       -> ReadinessOut
GET /api/v1/subjects/{subject_id}/next?limit=5                 -> RecommendationsOut
```

```ts
type GraphOut = {
  nodes: Array<{ id: string; kind: "concept" | "skill"; label: string; category?: string
                 difficulty?: number; skills?: string[]; mastery?: number | null }>
  edges: Array<{ source: string; target: string; kind: "prerequisite" | "composes" | "analogue" | "evidences" }>
}

type ReadinessOut = {
  skill_id: string; title: string; ready: boolean; mastery: number | null
  blocking: Array<{ skill_id: string; title: string; mastery: number; required: number }>
  chain: string[]        // topologically ordered prerequisite skill ids
}

type RecommendationsOut = {
  subject_id: string
  recommendations: Array<{
    kind: "concept" | "practice" | "project" | "assessment" | "review"
    id: string; title: string; reason: string; score: number
    skill_id: string | null; target_difficulty: number | null
  }>
}
```

`reason` is a short human sentence — "IAM gates four skills you have not
started" — and is displayed verbatim. The recommender must produce it; the
frontend never composes one.

Readiness gate: a prerequisite skill blocks when its `overall < 0.6`. The
platform **warns but never hard-blocks**; a learner may always proceed. The
response says what they are missing, and the UI shows it as advice.

---

## Practice

```
GET  /api/v1/practice/{task_id}                              -> PracticeTaskOut
POST /api/v1/practice/{task_id}/attempts                     -> AttemptOut
POST /api/v1/practice/{task_id}/attempts/{attempt_id}/hint   -> HintOut
POST /api/v1/practice/{task_id}/attempts/{attempt_id}/submit  -> SubmissionResultOut
GET  /api/v1/practice/queue?subject_id=&skill_id=&limit=10   -> { tasks: PracticeSummary[] }
```

`PracticeTaskOut` is always the output of the schema model's `sanitized()`.
Answers, solutions, hidden test bodies, root causes and incident payloads are
never serialised before a pass. This is enforced in the schema layer, not the
route.

```ts
type AttemptOut = {
  attempt_id: string; task_id: string; started_at: string
  hints_used: number; submission_count: number
  time_limit_s: number | null
}

type HintOut = { level: number; md: string; hints_remaining: number; reveals_solution: boolean }

type SubmitIn =
  | { kind: "quiz"; answers: Record<string, string | string[] | Record<string, string>> }
  | { kind: "code" | "debug"; files: Array<{ path: string; content: string }> }
  | { kind: "sql"; sql: string }
  | { kind: "terminal"; commands: string[] }
  | { kind: "architecture"; nodes: ArchitectureNode[]; edges: Array<[string, string]> }
  | { kind: "incident"; inspected: string[]; remediations: string[]; root_cause?: string }

type SubmissionResultOut = {
  attempt_id: string; task_id: string
  passed: boolean; score: number; dimension: MasteryDimension
  hints_used: number; duration_ms: number
  feedback_md: string
  execution: ExecutionResult | null
  question_results: Array<{ question_id: string; correct: boolean
                            expected: unknown | null; explanation_md: string | null }> | null
  mastery_deltas: Array<{ skill_id: string; title: string; dimension: MasteryDimension
                          before: number; after: number
                          state: "untouched" | "partially_measured" | "developing" | "mastered" | "at_risk" }>
  unlocked_skills: string[]
  reveal: { solution_files?: Array<{ path: string; content: string }>
            root_cause_md?: string; correct_remediations?: string[] } | null
  next: { kind: string; id: string; title: string; reason: string } | null
}
```

`reveal` is populated when the learner passed, or when they exhausted the hint
ladder including a `reveals_solution` hint. `expected` inside `question_results`
is `null` for questions answered incorrectly on a non-final attempt of a graded
assessment; for ordinary practice it is always populated after grading.

---

## Execution

```
POST /api/v1/execution/runs        -> 200 ExecutionResult (sync) | 202 { execution_id }
GET  /api/v1/execution/runs/{id}   -> ExecutionResult
```

Runs under 5 seconds of declared timeout are executed inline and return `200`.
Anything longer is queued and returns `202` with a polling id. Ad-hoc runs are
rate limited per user and always use the tightest default limits, regardless of
what the caller asks for — a runnable snippet in a lesson cannot request the
network.

---

## Progress

```
GET /api/v1/progress/{subject_id}                        -> SubjectProgressOut
GET /api/v1/progress/{subject_id}/skills/{skill_id}      -> SkillDetailOut
GET /api/v1/progress/{subject_id}/history?days=30        -> { points: Array<{date, overall, skills_mastered}> }
```

```ts
type SubjectProgressOut = {
  subject_id: string
  summary: { overall: number; coverage: number
             skills_total: number; skills_mastered: number; skills_at_risk: number
             concepts_seen: number; practice_passed: number; projects_completed: number
             minutes_practised: number; streak_days: number }
  dimensions: Record<MasteryDimension, { score: number; measured: boolean }>
  skills: Array<{ skill_id: string; title: string; overall: number; coverage: number
                  state: string; ability: number
                  dimensions: Record<MasteryDimension, { score: number; measured: boolean }>
                  last_practiced_at: string | null }>
}

type SkillDetailOut = {
  skill: Skill
  mastery: SubjectProgressOut["skills"][number]
  evidence: Array<{ dimension: MasteryDimension; score: number; weight: number
                    source_type: string; source_id: string | null
                    hints_used: number; created_at: string; recency_factor: number }>
  readiness: ReadinessOut
  recommended_practice: PracticeSummary[]
}
```

Never render an unmeasured dimension as `0%`. `measured: false` means "no
evidence yet" and the UI shows a dash.

---

## Search and compare

```
GET /api/v1/search?q=...&subject_id=&kind=&limit=20   (auth optional) -> SearchOut
GET /api/v1/compare?ids=a,b,c                          (auth optional) -> CompareOut
```

```ts
type SearchOut = {
  query: string
  results: Array<{ id: string; kind: "concept" | "practice" | "project" | "skill" | "subject"
                   subject_id: string; title: string; snippet: string
                   score: number; matched_on: "title" | "keyword" | "body" | "error_text" }>
}

type CompareOut = {
  ids: string[]
  concepts: Concept[]
  rows: Array<{ facet: string; values: Record<string, string | null> }>
}
```

Search is hybrid: Postgres `tsvector` plus trigram similarity on titles and
keywords, with `common_errors[].error` indexed as its own field so that pasting
an error message finds the concept that explains it. A `pgvector` column exists
on the index table and is used when populated; the ranker degrades to lexical
only when it is null, so the platform runs with no embedding provider
configured.

Compare works across subjects via `Concept.analogues`. `facet` values come from
a fixed list: definition, purpose, components, dependencies, best practices,
production considerations, common errors.

---

## Admin and ingestion

All under `/api/v1/admin`, requires `is_admin`.

```
POST /api/v1/admin/subjects/reload                    -> { loaded: string[], failed: Array<{id, problems}> }
GET  /api/v1/admin/subjects/{id}/validate             -> { problems: string[], warnings: string[] }

GET  /api/v1/admin/ingestion/sources?subject_id=      -> { sources: SourceSpec[] }
POST /api/v1/admin/ingestion/sources                  -> SourceSpec
POST /api/v1/admin/ingestion/runs                     -> IngestionRun     // body: {subject_id, source_ids?, stages?, dry_run}
GET  /api/v1/admin/ingestion/runs?subject_id=         -> { runs: IngestionRun[] }
GET  /api/v1/admin/ingestion/runs/{run_id}            -> IngestionRun
GET  /api/v1/admin/ingestion/candidates?subject_id=&status=&target=  -> { candidates: ExtractionCandidate[] }
POST /api/v1/admin/ingestion/candidates/{id}/review   -> ExtractionCandidate  // body: {decision, notes?, payload?}
GET  /api/v1/admin/provenance/{entity_id}             -> ProvenanceTrailOut
```

```ts
type ProvenanceTrailOut = {
  entity_id: string; entity_kind: string
  provenance: Provenance
  sources: SourceRef[]
  chain: Array<{ stage: string; id: string; label: string; detail: string | null }>
}
```

The provenance trail answers "where did this statement come from" by walking
source → document → chunk → candidate → published entity. An admin UI that
cannot answer that question makes the platform untrustworthy for infrastructure
and financial content, so the endpoint is part of the MVP surface even though the
extractor behind it is a stub.

`decision` is one of `approve`, `reject`, `request_changes`. Approving a
candidate does **not** publish it; a separate build step writes an approved
candidate into the package directory and bumps the version.

---

## What the frontend is not allowed to do

- Compose recommendation or feedback text. Both arrive from the API.
- Compute mastery. It renders `progress` as given.
- Hold a subject-specific `if` statement. Behaviour comes from `mode_layouts`
  and the panel registry. A new subject must require zero frontend changes; if it
  does not, the layout vocabulary is missing a panel and that is the fix.
- Trust `sanitized()` to have happened upstream and then log the payload
  anywhere a learner can read it.
