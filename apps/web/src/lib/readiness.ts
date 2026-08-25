import type { ReadyOut } from "./types";

/**
 * What to tell a learner when a dependency is degraded, and when to say nothing.
 *
 * Pure and separate from the banner that renders it, because the interesting part
 * is the decision rather than the markup, and a decision in a component body can
 * only be checked by rendering it.
 *
 * Two rules, both learned from a real local run:
 *
 * 1. Every warning names the consequence *for that dependency*. The banner used to
 *    end every message with "practice submissions may fail until service recovers"
 *    no matter what was down, which was false for three of the four cases. Nothing
 *    on the submit path touches Redis, and a sandbox outage still grades quizzes
 *    and written answers.
 * 2. A degraded cache produces no warning at all. Redis backs progress-rollup
 *    caching, subject-runtime caching and the rate-limit windows; all three fail
 *    open (`cache.incr_window` returns 0 when Redis is unreachable), so a learner
 *    cannot tell the difference except in page latency. `make dev-local` runs with
 *    no Redis on purpose, so warning about it meant a permanent yellow strip on
 *    every page for a deliberate configuration, which is how a banner teaches
 *    people to ignore banners. `/readyz` still reports `redis: false` and still
 *    says `degraded`, so the operator signal is intact; it just does not belong in
 *    the learner's face.
 *
 * The API side of rule 2 is pinned by
 * `apps/api/tests/test_validation_errors.py::test_a_submission_still_works_with_the_cache_unreachable`,
 * which runs a real attempt and submission against an unreachable Redis.
 */
export type Readiness = {
  /** One sentence per degraded dependency, cause then consequence. Empty means nothing to say. */
  issues: string[];
  /**
   * Render in the danger colour rather than the warning colour. True for the two
   * outages that stop the product working at all: no API to talk to, and no
   * database behind it. A missing sandbox is amber because most of the catalogue
   * and all of the quizzes still work.
   */
  severe: boolean;
};

export function readinessIssues(ready: ReadyOut | undefined, isError: boolean): Readiness {
  if (isError || !ready) {
    return {
      issues: ["The API is unreachable. Nothing on this page is live until it answers again."],
      severe: true,
    };
  }

  const issues: string[] = [];
  if (!ready.postgres) {
    // Reachable with no error: `/readyz` answers 503 when Postgres is down, and
    // `fetchReadiness` deliberately parses that body instead of throwing, because
    // the 503 and the 200 carry the same shape.
    issues.push("The database is down. Signing in, saving work and progress are unavailable.");
  }
  if (ready.sandbox === "unavailable") {
    issues.push(
      "The execution sandbox is offline. Code and debugging tasks cannot run; quizzes and written answers still grade normally.",
    );
  }
  // `ready.redis === false` deliberately contributes nothing. See rule 2 above.
  return { issues, severe: !ready.postgres };
}
