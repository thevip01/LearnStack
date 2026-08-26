import { test } from "node:test";
import assert from "node:assert/strict";
import { PANEL_WRITES, loginHref, needsSession, redirectsOn401, writingPanelTypes } from "./authGate.ts";
import type { PanelType } from "./types.ts";

const panels = (...types: PanelType[]) => types.map((type) => ({ type }));

test("a reading-only layout needs no account", () => {
  assert.equal(needsSession(panels("curriculum", "content", "sources", "concept_meta")), false);
});

test("a quiz in the layout needs an account", () => {
  assert.equal(needsSession(panels("curriculum", "content", "quiz")), true);
});

test("so does a code editor, a terminal, a canvas or a hint ladder", () => {
  for (const type of ["code_editor", "terminal", "sql_console", "architecture_canvas", "incident_console", "hints"] as PanelType[]) {
    assert.equal(needsSession(panels("content", type)), true, `${type} should require a session`);
  }
});

test("an empty layout needs nothing", () => {
  assert.equal(needsSession([]), false);
});

test("the panels that write are exactly the ones with a POST behind them", () => {
  assert.deepEqual(writingPanelTypes().sort(), [
    "architecture_canvas",
    "code_editor",
    "hints",
    "incident_console",
    "quiz",
    "sql_console",
    "terminal",
  ]);
});

test("mastery and progress panels stay open: reading your own dash is not a write", () => {
  assert.equal(PANEL_WRITES.mastery, false);
  assert.equal(PANEL_WRITES.chart, false);
});

test("loginHref carries the current location back", () => {
  assert.equal(loginHref("/subjects/programming.python/practice"), "/login?next=%2Fsubjects%2Fprogramming.python%2Fpractice");
});

test("loginHref does not send /login back to itself", () => {
  assert.equal(loginHref("/login"), "/login");
});

test("loginHref survives a missing or odd pathname", () => {
  assert.equal(loginHref(""), "/login?next=%2F");
  assert.equal(loginHref("subjects"), "/login?next=%2F");
});

test("a refused write sends the learner to sign in", () => {
  assert.equal(redirectsOn401("/practice/x/attempts", "POST"), true);
  assert.equal(redirectsOn401("/practice/x/attempts/1/submit", "POST"), true);
  assert.equal(redirectsOn401("/projects/x/submissions", "PUT"), true);
  assert.equal(redirectsOn401("/notes/1", "PATCH"), true);
  assert.equal(redirectsOn401("/notes/1", "DELETE"), true);
});

test("a refused read is left to the panel that asked for it", () => {
  // Opening a practice workspace anonymously fires all three of these. While a
  // read redirected, the locked states on the overview were a promise the click
  // then broke: every one of these 401s threw the whole page at /login.
  assert.equal(redirectsOn401("/progress/programming.python", "GET"), false);
  assert.equal(redirectsOn401("/progress/programming.python/history", "GET"), false);
  assert.equal(redirectsOn401("/practice/x/attempts/latest", "GET"), false);
});

test("an omitted method counts as a read", () => {
  // Every query in queries.ts relies on apiFetch defaulting to GET.
  assert.equal(redirectsOn401("/progress/programming.python", undefined), false);
});

test("auth endpoints never redirect, whatever the method", () => {
  assert.equal(redirectsOn401("/auth/me", "GET"), false);
  assert.equal(redirectsOn401("/auth/login", "POST"), false);
  assert.equal(redirectsOn401("/auth/register", "POST"), false);
  assert.equal(redirectsOn401("/auth/logout", "POST"), false);
});
