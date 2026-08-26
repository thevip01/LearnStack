/**
 * The first automated test in the web app, and it exists because of a defect that
 * three offline gates, a typecheck, a build and a 250-test backend suite all had
 * no way to see: registration succeeded and the learner was bounced straight back
 * to /login. Nothing was broken in the auth code. The app was served on one
 * spelling of localhost and told to call the other, which makes every request
 * cross-site, and a SameSite=Lax cookie is silently withheld from those.
 *
 * Run with `make test-web-unit`, or directly:
 *   node --experimental-strip-types --test src/lib/apiTarget.test.ts
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { looksSameSite, resolveApiTarget, SERVER_FALLBACK } from "./apiTarget.ts";

const PAGE = "http://localhost:3000";

test("the browser calls its own origin when nothing is configured", () => {
  const target = resolveApiTarget({}, PAGE);
  assert.equal(target.base, PAGE);
  assert.equal(target.warning, null);
});

test("the server uses the internal hostname, which the browser cannot resolve", () => {
  const target = resolveApiTarget({ internal: "http://api:8000" }, null);
  assert.equal(target.base, "http://api:8000");
  assert.equal(target.warning, null);
});

test("the server falls back to the compose service name", () => {
  assert.equal(resolveApiTarget({}, null).base, SERVER_FALLBACK);
});

test("the server prefers the internal hostname over the public one", () => {
  const target = resolveApiTarget({ internal: "http://api:8000", public: "https://api.example.com" }, null);
  assert.equal(target.base, "http://api:8000");
});

test("the exact defect: localhost page, 127.0.0.1 API, warned about by name", () => {
  const target = resolveApiTarget({ public: "http://127.0.0.1:8000" }, PAGE);
  assert.equal(target.base, "http://127.0.0.1:8000");
  assert.ok(target.warning, "an arrangement that drops the session cookie must not be silent");
  assert.match(target.warning, /SameSite=Lax/);
  assert.match(target.warning, /127\.0\.0\.1/);
  assert.match(target.warning, /localhost/);
});

test("the reverse spelling is just as broken", () => {
  const target = resolveApiTarget({ public: "http://localhost:8000" }, "http://127.0.0.1:3000");
  assert.ok(target.warning);
});

test("an explicit API on the same host is fine, whatever the port", () => {
  const target = resolveApiTarget({ public: "http://localhost:8000" }, PAGE);
  assert.equal(target.base, "http://localhost:8000");
  assert.equal(target.warning, null);
});

test("a deployed API on a sibling subdomain is same-site and stays silent", () => {
  const target = resolveApiTarget({ public: "https://api.learnos.dev" }, "https://app.learnos.dev");
  assert.equal(target.base, "https://api.learnos.dev");
  assert.equal(target.warning, null);
});

test("a genuinely different domain is called out", () => {
  const target = resolveApiTarget({ public: "https://api.somewhere-else.net" }, "https://app.learnos.dev");
  assert.ok(target.warning);
});

test("a blank override is treated as unset, not as an empty base", () => {
  assert.equal(resolveApiTarget({ public: "   " }, PAGE).base, PAGE);
  assert.equal(resolveApiTarget({ public: "" }, PAGE).base, PAGE);
});

test("garbage in the override falls back to this origin and says why", () => {
  const target = resolveApiTarget({ public: "not a url" }, PAGE);
  assert.equal(target.base, PAGE);
  assert.match(target.warning ?? "", /not a URL/);
});

test("looksSameSite: the cases the rule turns on", () => {
  assert.equal(looksSameSite("localhost", "localhost"), true);
  assert.equal(looksSameSite("localhost", "127.0.0.1"), false);
  assert.equal(looksSameSite("api.learnos.dev", "app.learnos.dev"), true);
  assert.equal(looksSameSite("learnos.dev", "api.learnos.dev"), true);
  assert.equal(looksSameSite("learnos.dev", "learnos.io"), false);
  // Two IPs in the same /24 are not one site. Label comparison happens to agree.
  assert.equal(looksSameSite("192.168.1.10", "192.168.1.11"), false);
});
