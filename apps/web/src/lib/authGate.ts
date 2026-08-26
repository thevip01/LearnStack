import type { PanelType } from "./types";

/**
 * Which parts of a subject need an account, decided from the package rather than
 * from a list of mode names.
 *
 * The API is deliberately readable by anyone: every GET on a subject, a concept or
 * a practice task takes an optional user, so a visitor can read the whole
 * curriculum without signing up. What needs a session is *acting*: starting an
 * attempt, taking a hint, submitting an answer. All three are POSTs behind
 * `CurrentUser`, so they answer 401 to an anonymous caller.
 *
 * Before this existed, that was a fine contract with a bad delivery. Nothing on
 * screen said an account was needed, so the way you found out was to answer five
 * quiz questions, press Submit, and get thrown at /login with the answers gone.
 * The remedy is to say it in advance, in the places where the choice is made, and
 * to leave the reading open, because a wall in front of the content would trade
 * one bad experience for a worse one.
 *
 * `PANEL_WRITES` is typed `Record<PanelType, boolean>`, so a new panel type cannot
 * be added without deciding this question, and `tools/check_web.py` checks the map
 * for exhaustiveness in both directions. A `false` here is a claim that the panel
 * has no action the API would refuse.
 */
export const PANEL_WRITES: Record<PanelType, boolean> = {
  // Reading, navigation and display. Nothing here posts.
  curriculum: false,
  content: false,
  concept_meta: false,
  instructions: false,
  file_explorer: false,
  console: false,
  test_results: false,
  diagram: false,
  cloud_topology: false,
  dataset_viewer: false,
  metrics: false,
  chart: false,
  trading_chart: false,
  browser_preview: false,
  api_client: false,
  http_inspector: false,
  simulation_canvas: false,
  tutor: false,
  mastery: false,
  project_brief: false,
  sources: false,
  // Flashcards keep their state in the workspace store and grade nothing, which is
  // why they are readable anonymously. If they ever record retention evidence this
  // flips, and the type will not let anyone forget.
  flashcards: false,
  notebook: false,

  // Every one of these ends in an attempt, a hint or a submission.
  quiz: true,
  code_editor: true,
  terminal: true,
  sql_console: true,
  architecture_canvas: true,
  incident_console: true,
  hints: true,
};

/**
 * True when a layout contains anything a signed-out visitor cannot finish.
 *
 * Takes just the panel types so the decision is testable without building a whole
 * runtime object, and so a caller cannot accidentally pass the wrong mode's panels
 * and have it still typecheck.
 */
export function needsSession(panels: readonly { type: PanelType }[]): boolean {
  return panels.some((panel) => PANEL_WRITES[panel.type]);
}

/** The writing panels, listed. Used by the tests and by anything explaining the rule. */
export function writingPanelTypes(): PanelType[] {
  return (Object.keys(PANEL_WRITES) as PanelType[]).filter((type) => PANEL_WRITES[type]);
}

/**
 * Where a locked affordance sends someone, preserving where they were.
 *
 * Built from `usePathname()` rather than `window.location`, because these render
 * during SSR too and reading `window` there is a crash rather than a fallback.
 */
export function loginHref(pathname: string): string {
  const target = pathname && pathname.startsWith("/") ? pathname : "/";
  if (target === "/login") return "/login";
  return `/login?next=${encodeURIComponent(target)}`;
}

/**
 * Which 401 interrupts the reader, and which one the page absorbs.
 *
 * A 401 answers two different questions and they need opposite handling. "You
 * tried to submit an attempt without an account" is worth interrupting for: the
 * learner asked for something, the answer is sign in first, and `?next=` brings
 * them back to the task. "This panel wanted your mastery history and you are
 * reading anonymously" is not: the panel knows how to say so itself, and every one
 * that can 401 renders its own sign-in state.
 *
 * Redirecting on reads collapsed the whole design. Opening
 * /subjects/programming.python/practice as a visitor puts a mastery panel and a
 * history chart on screen, both GETs behind a session, and the first 401 threw the
 * page at /login. The overview promised "open to read, sign in to attempt" and the
 * click bounced anyway, which is worse than shipping no lock at all: a signup wall
 * that also lies about itself. Caught in a browser, not by a type.
 *
 * Auth endpoints are exempt in both directions. /auth/me is how the shell probes
 * for a session, so its 401 is the expected answer for a visitor, and /auth/login
 * answering 401 means the password was wrong, which the form reports in place.
 *
 * The caller checks for a browser; this stays pure so it can be tested.
 */
export function redirectsOn401(path: string, method: string | undefined): boolean {
  if (path.startsWith("/auth/")) return false;
  // `apiFetch` defaults to GET, so an omitted method is a read.
  return method !== undefined && method !== "GET";
}
