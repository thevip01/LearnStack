/**
 * Transcribed from docs/architecture/10-contracts.md and
 * packages/knowledge-schema/learnos_schema/*.py. This file is the only place the
 * frontend is allowed to describe the wire format; if it disagrees with the
 * contract document, the document wins.
 *
 * Practice payloads are the output of the schema layer's `sanitized()`, so the
 * secret-bearing fields (answers, hidden test bodies, root causes, incident
 * payloads) are simply absent from these types. That is deliberate: if a field
 * cannot be named here, no component can render it by accident.
 */

// ---------------------------------------------------------------------------
// Primitives and enums
// ---------------------------------------------------------------------------

export type LearningMode = "learn" | "practice" | "lab" | "project" | "production" | "exam" | "review";

export const LEARNING_MODES: readonly LearningMode[] = [
  "learn",
  "practice",
  "lab",
  "project",
  "production",
  "exam",
  "review",
] as const;

export type MasteryDimension = "concept" | "practice" | "lab" | "debugging" | "production" | "retention";

export const MASTERY_DIMENSIONS: readonly MasteryDimension[] = [
  "concept",
  "practice",
  "lab",
  "debugging",
  "production",
  "retention",
] as const;

export type LifecycleStatus = "draft" | "in_review" | "approved" | "published" | "deprecated";

export type SourceType =
  | "documentation"
  | "api_reference"
  | "architecture"
  | "standard"
  | "rfc"
  | "repository"
  | "tutorial"
  | "article"
  | "book"
  | "dataset"
  | "course"
  | "first_party";

export type RuntimeKind =
  | "python"
  | "node"
  | "browser"
  | "sql"
  | "bash"
  | "terraform"
  | "notebook"
  | "cloud_sim"
  | "market_sim"
  | "none";

export type MasteryState = "untouched" | "partially_measured" | "developing" | "mastered" | "at_risk";

export type PracticeKind = "quiz" | "code" | "debug" | "sql" | "terminal" | "api" | "architecture" | "incident";

export type SourceRef = {
  source_id: string;
  url: string | null;
  title: string | null;
  source_type: SourceType;
  published_at: string | null;
  retrieved_at: string | null;
  content_hash: string | null;
  locator: string | null;
  confidence: number;
};

export type Provenance = {
  generator: string;
  generated_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  status: LifecycleStatus;
  notes: string | null;
};

// ---------------------------------------------------------------------------
// UI schema (ui.py): the panel vocabulary
// ---------------------------------------------------------------------------

export type PanelType =
  | "curriculum"
  | "content"
  | "concept_meta"
  | "instructions"
  | "code_editor"
  | "file_explorer"
  | "console"
  | "terminal"
  | "test_results"
  | "quiz"
  | "flashcards"
  | "diagram"
  | "architecture_canvas"
  | "cloud_topology"
  | "sql_console"
  | "notebook"
  | "dataset_viewer"
  | "metrics"
  | "chart"
  | "trading_chart"
  | "browser_preview"
  | "api_client"
  | "http_inspector"
  | "simulation_canvas"
  | "incident_console"
  | "tutor"
  | "hints"
  | "mastery"
  | "project_brief"
  | "sources";

export type Slot = "left" | "main" | "right" | "bottom";

export const SLOTS: readonly Slot[] = ["left", "main", "right", "bottom"] as const;

export type Panel = {
  id: string;
  type: PanelType;
  slot: Slot;
  title: string | null;
  /** Passed to the component untouched. Never interpreted by the layout. */
  config: Record<string, unknown>;
  collapsible: boolean;
  default_collapsed: boolean;
  min_width: number | null;
  min_height: number | null;
  flex: number;
};

export type ModeLayout = {
  label: string | null;
  panels: Panel[];
  primary_slot: Slot;
};

export type ThemeSpec = {
  accent: string;
  accent_soft: string | null;
  icon: string | null;
  mono_font: string | null;
  density: "comfortable" | "compact";
};

export type NavigationItem = {
  id: string;
  title: string;
  kind: "track" | "module" | "concept" | "project" | "assessment" | "lab";
  depth: number;
  parent_id: string | null;
  icon: string | null;
  estimated_minutes: number | null;
  skills: string[];
};

// ---------------------------------------------------------------------------
// Content blocks (content.py)
// ---------------------------------------------------------------------------

export type ProseBlock = { type: "prose"; md: string; sources: SourceRef[] };

export type CodeBlock = {
  type: "code";
  runtime: RuntimeKind;
  language: string | null;
  code: string;
  caption: string | null;
  runnable: boolean;
  expected_output: string | null;
  highlight_lines: number[];
};

export type CalloutBlock = {
  type: "callout";
  variant: "note" | "tip" | "warning" | "danger" | "production";
  title: string | null;
  md: string;
};

export type DiagramBlock = {
  type: "diagram";
  format: "mermaid" | "ascii" | "topology";
  source: string;
  caption: string | null;
  interactive: boolean;
};

export type TableBlock = { type: "table"; columns: string[]; rows: string[][]; caption: string | null };

export type StepsBlock = { type: "steps"; title: string | null; steps: string[] };

export type CommandBlock = {
  type: "command";
  shell: "bash" | "powershell" | "sql";
  commands: string[];
  caption: string | null;
  copyable: boolean;
};

export type TermBlock = { type: "term"; term: string; definition_md: string; aliases: string[] };

export type EmbedPracticeBlock = { type: "embed_practice"; practice_id: string };

export type ContentBlock =
  | ProseBlock
  | CodeBlock
  | CalloutBlock
  | DiagramBlock
  | TableBlock
  | StepsBlock
  | CommandBlock
  | TermBlock
  | EmbedPracticeBlock;

// ---------------------------------------------------------------------------
// Curriculum, concepts, skills
// ---------------------------------------------------------------------------

export type Module = {
  id: string;
  title: string;
  summary: string | null;
  concepts: string[];
  projects: string[];
  labs: string[];
  assessment_id: string | null;
  estimated_minutes: number | null;
  icon: string | null;
};

export type Track = { id: string; title: string; summary: string | null; modules: Module[]; goal: string | null };

export type Skill = {
  id: string;
  title: string;
  description: string | null;
  concepts: string[];
  prerequisites: string[];
  difficulty: number;
  dimension_weights: Partial<Record<MasteryDimension, number>> | null;
  external_analogues: string[];
};

export type CommonError = { error: string; cause: string; fix: string; sources: SourceRef[] };

export type Example = {
  title: string;
  md: string | null;
  code: string | null;
  language: string | null;
  output: string | null;
};

export type ConceptComponent = { name: string; role: string; required: boolean };

export type Concept = {
  id: string;
  title: string;
  subject_id: string;
  category: string;
  summary: string;
  definition: string;
  purpose: string;
  body: ContentBlock[];
  components: ConceptComponent[];
  dependencies: string[];
  prerequisites: string[];
  related: string[];
  analogues: string[];
  common_errors: CommonError[];
  best_practices: string[];
  production_considerations: string[];
  anti_patterns: string[];
  examples: Example[];
  skills: string[];
  practice: string[];
  keywords: string[];
  estimated_minutes: number;
  sources: SourceRef[];
  provenance: Provenance;
};

export type RuntimeSpec = {
  id: string;
  kind: RuntimeKind;
  version: string;
  image: string;
  default_command: string;
  packages: string[];
  supports_tests: boolean;
  supports_interactive: boolean;
};

// ---------------------------------------------------------------------------
// Practice tasks, as sanitised for the wire (practice.py `sanitized()`)
// ---------------------------------------------------------------------------

export type QuestionOption = { id: string; md: string };

/** `answer`, `explanation_md` and `must_include` are stripped by sanitize_question. */
type QuestionBase = {
  id: string;
  stem_md: string;
  difficulty: number;
  skills: string[];
  dimension: MasteryDimension;
  sources: SourceRef[];
  weight: number;
};

export type SafeMCQQuestion = QuestionBase & { type: "mcq"; options: QuestionOption[] };
export type SafeMultiSelectQuestion = QuestionBase & { type: "multi_select"; options: QuestionOption[] };
export type SafeFillBlankQuestion = QuestionBase & {
  type: "fill_blank";
  /** Blanks are marked `{{1}}`, `{{2}}` in the template. */
  template: string;
  case_sensitive: boolean;
};
export type SafeOrderingQuestion = QuestionBase & { type: "ordering"; items: QuestionOption[] };
export type SafeMatchingQuestion = QuestionBase & {
  type: "matching";
  left: QuestionOption[];
  right: QuestionOption[];
};
export type SafeShortAnswerQuestion = QuestionBase & { type: "short_answer" };

export type SafeQuestion =
  | SafeMCQQuestion
  | SafeMultiSelectQuestion
  | SafeFillBlankQuestion
  | SafeOrderingQuestion
  | SafeMatchingQuestion
  | SafeShortAnswerQuestion;

export type QuestionType = SafeQuestion["type"];

export type SourceFile = { path: string; content: string; readonly: boolean; hidden: boolean };

/** Hidden tests keep `name` (so a failure is actionable) and lose their body. */
export type TestCase = {
  id: string;
  name: string;
  kind: "pytest" | "unittest" | "jest" | "io" | "sql" | "assertion";
  visible: boolean;
  weight: number;
  file: string | null;
  body: string | null;
  stdin: string | null;
  expected_stdout: string | null;
  timeout_s: number | null;
};

export type SandboxLimits = {
  runtime: RuntimeKind;
  runtime_version: string | null;
  timeout_s: number;
  memory_mb: number;
  cpu_limit: number;
  pids_limit: number;
  network: "none" | "egress_allowlist" | "full";
  egress_allowlist: string[];
  packages: string[];
};

export type RubricCriterion = {
  id: string;
  description: string;
  weight: number;
  dimension: MasteryDimension;
  automated: boolean;
};

export type Evaluation = {
  strategy: "exact" | "pytest" | "unit_tests" | "sql_result" | "state_match" | "rubric" | "simulation";
  pass_threshold: number;
  rubric: RubricCriterion[];
  partial_credit: boolean;
  dimension: MasteryDimension;
};

export type ArchitectureNode = { id: string; type: string; label: string | null; config: Record<string, unknown> };

export type IncidentSignalSurface = "metric" | "log" | "trace" | "config" | "deployment" | "topology" | "alert";

/**
 * `payload`, `is_red_herring` and `reveals` are removed by IncidentTask.sanitized(),
 * so payload is optional here: the console renders it when a future inspect
 * endpoint supplies it and shows a withheld state otherwise.
 */
export type SafeIncidentSignal = {
  id: string;
  surface: IncidentSignalSurface;
  name: string;
  payload?: string | null;
};

type PracticeTaskCommon = {
  id: string;
  title: string;
  subject_id: string;
  concept_id: string | null;
  skills: string[];
  difficulty: number;
  estimated_minutes: number;
  prompt_md: string;
  /** `hints` is replaced by `hint_count` in public_fields(). */
  hint_count: number;
  tags: string[];
  sources: SourceRef[];
  provenance: Provenance;
  evaluation: Evaluation;
};

export type QuizTaskOut = PracticeTaskCommon & {
  kind: "quiz";
  questions: SafeQuestion[];
  shuffle: boolean;
  time_limit_s: number | null;
};

export type CodeTaskOut = PracticeTaskCommon & {
  kind: "code";
  environment: SandboxLimits;
  starter_files: SourceFile[];
  tests: TestCase[];
  entrypoint: string;
  run_command: string | null;
  requirements_md: string[];
};

export type DebugTaskOut = Omit<CodeTaskOut, "kind"> & { kind: "debug"; symptom_md: string };

export type SQLTaskOut = PracticeTaskCommon & {
  kind: "sql";
  environment: SandboxLimits;
  schema_sql: string;
  seed_sql: string | null;
  ordered: boolean;
};

export type TerminalTaskOut = PracticeTaskCommon & {
  kind: "terminal";
  environment: SandboxLimits;
  initial_filesystem: SourceFile[];
  goal_checks: TestCase[];
  allowed_commands: string[];
};

export type APITaskOut = PracticeTaskCommon & { kind: "api"; base_url: string; requests_spec_md: string | null };

export type ArchitectureTaskOut = PracticeTaskCommon & {
  kind: "architecture";
  palette: string[];
  initial_nodes: ArchitectureNode[];
  initial_edges: string[][];
  constraints_md: string[];
  target_properties: string[];
};

export type IncidentTaskOut = PracticeTaskCommon & {
  kind: "incident";
  scenario_md: string;
  architecture_md: string | null;
  symptoms: string[];
  signals: SafeIncidentSignal[];
  remediations: QuestionOption[];
  max_inspections: number | null;
};

export type PracticeTaskOut =
  | QuizTaskOut
  | CodeTaskOut
  | DebugTaskOut
  | SQLTaskOut
  | TerminalTaskOut
  | APITaskOut
  | ArchitectureTaskOut
  | IncidentTaskOut;

/** Tasks that hand the learner a file tree. */
export type FileBearingTask = CodeTaskOut | DebugTaskOut | TerminalTaskOut;

// ---------------------------------------------------------------------------
// Execution (execution.py)
// ---------------------------------------------------------------------------

export type ExecutionStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "timeout"
  | "oom"
  | "cancelled"
  | "internal_error";

export type TestResult = {
  test_id: string;
  name: string;
  passed: boolean;
  weight: number;
  duration_ms: number | null;
  message: string | null;
  traceback: string | null;
};

export type ResourceUsage = {
  duration_ms: number;
  max_memory_mb: number | null;
  cpu_ms: number | null;
  exit_code: number | null;
};

export type ExecutionResult = {
  execution_id: string;
  status: ExecutionStatus;
  stdout: string;
  stderr: string;
  truncated: boolean;
  usage: ResourceUsage;
  tests: TestResult[];
  artifacts: Record<string, string>;
  runner: "docker" | "subprocess";
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type ExecutionRequest = {
  files: Array<Pick<SourceFile, "path" | "content">>;
  limits?: Partial<SandboxLimits>;
  command?: string | null;
  stdin?: string | null;
};

/** POST /execution/runs answers 200 with a result or 202 with a polling id. */
export type ExecutionAccepted = { execution_id: string };
export type ExecutionRunResponse = ExecutionResult | ExecutionAccepted;

export function isExecutionAccepted(value: ExecutionRunResponse): value is ExecutionAccepted {
  return !("status" in value);
}

// ---------------------------------------------------------------------------
// HTTP envelopes (10-contracts.md)
// ---------------------------------------------------------------------------

export type ApiErrorCode =
  | "bad_request"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "unprocessable"
  | "rate_limited"
  | "sandbox_unavailable"
  | "internal_error";

export type ApiErrorEnvelope = { error: { code: ApiErrorCode; message: string; detail: unknown } };

export type HealthOut = { status: string; version: string };

export type ReadyOut = {
  status: string;
  postgres: boolean;
  redis: boolean;
  sandbox: "docker" | "subprocess" | "unavailable";
};

export type UserOut = {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
  is_admin: boolean;
};

export type AuthOut = { access_token: string; token_type: "bearer"; expires_in: number; user: UserOut };

export type CatalogSubject = {
  id: string;
  title: string;
  subtitle: string | null;
  description: string;
  provider: string | null;
  version: string;
  status: string;
  theme: ThemeSpec;
  tags: string[];
  concept_count: number;
  practice_count: number;
  project_count: number;
  estimated_minutes: number;
  progress: { overall: number; skills_mastered: number; skills_total: number } | null;
};

export type CatalogOut = {
  domains: Array<{ id: string; title: string; icon: string | null; subjects: CatalogSubject[] }>;
};

export type SubjectRuntimeOut = {
  id: string;
  title: string;
  subtitle: string | null;
  description: string;
  domain: { id: string; title: string; icon: string | null };
  provider: string | null;
  version: string;
  content_hash: string;
  status: string;
  theme: ThemeSpec;
  layout: "learning_lab" | "ml_workbench" | "trading_desk" | "reader" | "canvas";
  default_mode: LearningMode;
  modes: LearningMode[];
  /** Already merged with global_panels server-side. */
  mode_layouts: Partial<Record<LearningMode, ModeLayout>>;
  navigation: NavigationItem[];
  tracks: Track[];
  skills: Skill[];
  runtimes: RuntimeSpec[];
  progress: SubjectProgressOut | null;
};

export type PracticeSummary = {
  id: string;
  kind: PracticeKind;
  title: string;
  difficulty: number;
  estimated_minutes: number;
  hint_count: number;
  skills: string[];
  state: "untouched" | "in_progress" | "passed" | "failed";
  best_score: number | null;
  attempts: number;
};

export type ConceptOut = Concept & {
  practice: PracticeSummary[];
  prerequisite_status: Array<{ concept_id: string; title: string; mastery: number | null; ready: boolean }>;
  next_concept_id: string | null;
  prev_concept_id: string | null;
  module: { id: string; title: string; track_id: string; track_title: string } | null;
};

export type GraphOut = {
  nodes: Array<{
    id: string;
    kind: "concept" | "skill";
    label: string;
    category?: string;
    difficulty?: number;
    skills?: string[];
    mastery?: number | null;
  }>;
  edges: Array<{
    source: string;
    target: string;
    kind: "prerequisite" | "composes" | "analogue" | "evidences";
  }>;
};

export type ReadinessOut = {
  skill_id: string;
  title: string;
  ready: boolean;
  mastery: number | null;
  blocking: Array<{ skill_id: string; title: string; mastery: number; required: number }>;
  chain: string[];
};

export type Recommendation = {
  kind: "concept" | "practice" | "project" | "assessment" | "review";
  id: string;
  title: string;
  /** A human sentence from the recommender. Rendered verbatim, never composed here. */
  reason: string;
  score: number;
  skill_id: string | null;
  target_difficulty: number | null;
};

export type RecommendationsOut = { subject_id: string; recommendations: Recommendation[] };

export type AttemptOut = {
  attempt_id: string;
  task_id: string;
  started_at: string;
  hints_used: number;
  submission_count: number;
  time_limit_s: number | null;
};

export type HintOut = { level: number; md: string; hints_remaining: number; reveals_solution: boolean };

export type QuizAnswerMap = Record<string, string | string[] | Record<string, string>>;

export type SubmitIn =
  | { kind: "quiz"; answers: QuizAnswerMap }
  | { kind: "code" | "debug"; files: Array<{ path: string; content: string }> }
  | { kind: "sql"; sql: string }
  | { kind: "terminal"; commands: string[] }
  | { kind: "architecture"; nodes: ArchitectureNode[]; edges: Array<[string, string]> }
  | { kind: "incident"; inspected: string[]; remediations: string[]; root_cause?: string };

export type MasteryDelta = {
  skill_id: string;
  title: string;
  dimension: MasteryDimension;
  before: number;
  after: number;
  state: MasteryState;
};

export type QuestionResult = {
  question_id: string;
  correct: boolean;
  expected: unknown | null;
  explanation_md: string | null;
};

export type SubmissionResultOut = {
  attempt_id: string;
  task_id: string;
  passed: boolean;
  score: number;
  dimension: MasteryDimension;
  hints_used: number;
  duration_ms: number;
  /** Authored/graded prose from the API. Rendered verbatim. */
  feedback_md: string;
  execution: ExecutionResult | null;
  question_results: QuestionResult[] | null;
  mastery_deltas: MasteryDelta[];
  unlocked_skills: string[];
  reveal: {
    solution_files?: Array<{ path: string; content: string }>;
    root_cause_md?: string;
    correct_remediations?: string[];
  } | null;
  next: { kind: string; id: string; title: string; reason: string } | null;
};

/** `measured: false` means "no evidence yet". The UI renders a dash, never 0%. */
export type DimensionScore = { score: number; measured: boolean };

export type DimensionMap = Partial<Record<MasteryDimension, DimensionScore>>;

export type SkillMasteryOut = {
  skill_id: string;
  title: string;
  overall: number;
  coverage: number;
  state: string;
  ability: number;
  dimensions: DimensionMap;
  last_practiced_at: string | null;
};

export type SubjectProgressOut = {
  subject_id: string;
  summary: {
    overall: number;
    coverage: number;
    skills_total: number;
    skills_mastered: number;
    skills_at_risk: number;
    concepts_seen: number;
    practice_passed: number;
    projects_completed: number;
    minutes_practised: number;
    streak_days: number;
  };
  dimensions: DimensionMap;
  skills: SkillMasteryOut[];
};

export type EvidenceRow = {
  dimension: MasteryDimension;
  score: number;
  weight: number;
  source_type: string;
  source_id: string | null;
  hints_used: number;
  created_at: string;
  recency_factor: number;
};

export type SkillDetailOut = {
  skill: Skill;
  mastery: SkillMasteryOut;
  evidence: EvidenceRow[];
  readiness: ReadinessOut;
  recommended_practice: PracticeSummary[];
};

export type HistoryOut = { points: Array<{ date: string; overall: number; skills_mastered: number }> };

export type SearchResult = {
  id: string;
  kind: "concept" | "practice" | "project" | "skill" | "subject";
  subject_id: string;
  title: string;
  snippet: string;
  score: number;
  matched_on: "title" | "keyword" | "body" | "error_text";
};

export type SearchOut = { query: string; results: SearchResult[] };

export type CompareOut = {
  ids: string[];
  concepts: Concept[];
  rows: Array<{ facet: string; values: Record<string, string | null> }>;
};

// ---------------------------------------------------------------------------
// Admin / ingestion (ingestion.py)
// ---------------------------------------------------------------------------

export type AdapterKind = "web" | "sitemap" | "rss" | "github" | "openapi" | "pdf" | "local";

export type FetchPolicy = {
  respect_robots: boolean;
  rate_limit_rps: number;
  max_pages: number;
  max_depth: number;
  user_agent: string;
  timeout_s: number;
  allow_patterns: string[];
  deny_patterns: string[];
  requires_auth: boolean;
  license_ack: string | null;
};

export type SourceSpec = {
  id: string;
  subject_id: string;
  title: string;
  adapter: AdapterKind;
  source_type: SourceType;
  entrypoint: string;
  priority: number;
  is_first_party: boolean;
  license: string | null;
  policy: FetchPolicy;
  enabled: boolean;
  last_run_at: string | null;
  notes: string | null;
};

export type IngestionStage =
  | "fetch"
  | "parse"
  | "clean"
  | "chunk"
  | "embed"
  | "extract"
  | "validate"
  | "review"
  | "build"
  | "publish";

export type StageReport = {
  stage: IngestionStage;
  started_at: string;
  finished_at: string | null;
  ok: boolean;
  items_in: number;
  items_out: number;
  skipped: number;
  messages: string[];
};

export type IngestionRun = {
  id: string;
  subject_id: string;
  source_ids: string[];
  target_version: string | null;
  dry_run: boolean;
  stages: StageReport[];
  started_at: string;
  finished_at: string | null;
  status: "running" | "succeeded" | "failed" | "cancelled";
};

export type ValidationIssue = {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  pointer: string | null;
};

export type ExtractionTarget = "concept" | "curriculum" | "practice" | "project" | "assessment";

export type ExtractionCandidate = {
  id: string;
  subject_id: string;
  target: ExtractionTarget;
  payload: Record<string, unknown>;
  chunk_ids: string[];
  confidence: number;
  issues: ValidationIssue[];
  duplicate_of: string | null;
  provenance: Provenance;
  status: LifecycleStatus;
};

export type ReviewDecision = "approve" | "reject" | "request_changes";

export type ProvenanceTrailOut = {
  entity_id: string;
  entity_kind: string;
  provenance: Provenance;
  sources: SourceRef[];
  chain: Array<{ stage: string; id: string; label: string; detail: string | null }>;
};
