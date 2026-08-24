#!/usr/bin/env bash
# Tier 3 of docs/architecture/11-verification.md, executable.
#
# Walks learn -> practice -> grade -> mastery against a running stack and asserts
# the invariants the prose claims, instead of asking a human to eyeball them. The
# code and debug submissions are read from the real subject package on disk, so a
# pass here means the grader actually graded a real solution rather than a fixture
# agreeing with itself.
#
# Usage:
#   make up && make verify-loop
#   API=http://localhost:8000 tools/verify_loop.sh
#
# Exit codes: 0 all checks passed, 1 a check failed, 2 the stack is not usable.
# Checks that cannot run on this machine (no sandbox) are SKIPped rather than
# failed: a missing Docker is a fact about the machine, not a defect in the code.

set -uo pipefail

API="${API:-http://localhost:${API_PORT:-8000}}"
V="$API/api/v1"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASKS="$REPO/subjects/programming/python/practice"

EMAIL="${LEARNOS_EMAIL:-demo@learnos.dev}"
PASSWORD="${LEARNOS_PASSWORD:-learnos-demo-2026}"

SUBJECT="programming.python"
QUIZ="python.practice.closures.check.late-binding"
CODE="python.practice.closures.code.counter-factory"
DEBUG="python.practice.closures.debug.late-binding-loop"
SKILL="python.skill.reason-about-closures"

# Every question in the quiz, so the second submission is a clean 5/5.
ALL_CORRECT='{"kind":"quiz","answers":{"closures.the-classic-loop":"a","closures.default-arg-capture":"a","closures.nonlocal-required":"a","closures.what-is-captured":["a","b"],"closures.shared-cell":"a"}}'
TWO_CORRECT='{"kind":"quiz","answers":{"closures.the-classic-loop":"a","closures.default-arg-capture":"a"}}'

WORK="$(mktemp -d)"
JAR="$WORK/cookies"
trap 'rm -rf "$WORK"' EXIT

PASSED=0
FAILED=0
SKIPPED=0
FAILURES=()

if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; B=$'\033[1m'; X=$'\033[0m'; else G=; R=; Y=; B=; X=; fi

ok()      { PASSED=$((PASSED + 1)); printf '  %sPASS%s %s\n' "$G" "$X" "$1"; }
bad()     { FAILED=$((FAILED + 1)); FAILURES+=("$1"); printf '  %sFAIL%s %s\n' "$R" "$X" "$1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
skipped() { SKIPPED=$((SKIPPED + 1)); printf '  %sSKIP%s %s\n' "$Y" "$X" "$1"; }
section() { printf '\n%s%s%s\n' "$B" "$1" "$X"; }

# --------------------------------------------------------------------------
# Helpers. python3 does the JSON so this needs no jq.
# --------------------------------------------------------------------------

# value <file> <python expression over d>
value() {
  python3 - "$1" "$2" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
v = eval(sys.argv[2])
print(v if not isinstance(v, (dict, list)) else json.dumps(v))
PY
}

# check <label> <file> <python expression over d>
check() {
  local label="$1" file="$2" expr="$3" rc
  python3 - "$file" "$expr" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"response was not json: {exc}", file=sys.stderr)
    sys.exit(2)
try:
    sys.exit(0 if eval(sys.argv[2]) else 1)
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(3)
PY
  rc=$?
  if [ "$rc" -eq 0 ]; then
    ok "$label"
  else
    bad "$label" "expected $expr, got $(head -c 400 "$file")"
  fi
}

# request <METHOD> <url> [json body] -> prints the path of the response file
request() {
  local method="$1" url="$2" body="${3:-}" out
  out="$WORK/response.$RANDOM.json"
  if [ -n "$body" ]; then
    curl -sS -b "$JAR" -c "$JAR" -X "$method" "$url" \
      -H 'content-type: application/json' -d "$body" -o "$out" -w '%{http_code}' > "$out.status"
  else
    curl -sS -b "$JAR" -c "$JAR" -X "$method" "$url" -o "$out" -w '%{http_code}' > "$out.status"
  fi
  printf '%s' "$out"
}

# submission_payload <task file> <kind> -> the reference solution as a submit body
submission_payload() {
  python3 - "$1" "$2" <<'PY'
import json, sys
task = json.load(open(sys.argv[1]))
files = task.get("solution_files") or []
if not files:
    raise SystemExit(f"{task['id']} ships no solution_files")
print(json.dumps({
    "kind": sys.argv[2],
    "files": [{"path": f["path"], "content": f["content"]} for f in files],
}))
PY
}

# --------------------------------------------------------------------------

section "Preflight"
READY="$(request GET "$API/readyz")"
if [ ! -s "$READY" ]; then
  printf '  nothing answered at %s/readyz: bring the stack up first (make up)\n' "$API"
  exit 2
fi
POSTGRES="$(value "$READY" "d['postgres']")"
SANDBOX="$(value "$READY" "d['sandbox']")"
printf '  %s  postgres=%s redis=%s sandbox=%s (http %s)\n' \
  "$(value "$READY" "d['status']")" "$POSTGRES" "$(value "$READY" "d['redis']")" "$SANDBOX" "$(cat "$READY.status")"
if [ "$POSTGRES" != "True" ]; then
  printf '  postgres is down, so nothing below can run\n'
  exit 2
fi
check "readyz stays 200 while only optional dependencies are degraded" "$READY" \
  "open('$READY.status').read() == '200'"

section "Auth"
LOGIN="$(request POST "$V/auth/login" "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
check "login returns a token" "$LOGIN" "bool(d.get('access_token'))"
ME="$(request GET "$V/auth/me")"
check "the cookie alone authenticates /auth/me" "$ME" "d['email'] == '$EMAIL'"

section "Practice queue"
QUEUE="$(request GET "$V/practice/queue?subject_id=$SUBJECT&limit=100")"
check "the queue offers the quiz" "$QUEUE" "any(t['id'] == '$QUIZ' for t in d['tasks'])"
check "the queue offers the code task" "$QUEUE" "any(t['id'] == '$CODE' for t in d['tasks'])"
check "the queue offers the debug task" "$QUEUE" "any(t['id'] == '$DEBUG' for t in d['tasks'])"
check "the queue is ordered easiest first" "$QUEUE" \
  "[t['difficulty'] for t in d['tasks']] == sorted(t['difficulty'] for t in d['tasks'])"
check "all three closures tasks feed one skill" "$QUEUE" \
  "all('$SKILL' in t['skills'] for t in d['tasks'] if t['id'] in {'$QUIZ','$CODE','$DEBUG'})"

section "Quiz: attempt, hint, grade"
FIRST="$(request POST "$V/practice/$QUIZ/attempts")"
ATTEMPT="$(value "$FIRST" "d['attempt_id']")"
SECOND="$(request POST "$V/practice/$QUIZ/attempts")"
check "reopening an attempt is idempotent, so paid-for hints survive a reload" "$SECOND" \
  "d['attempt_id'] == '$ATTEMPT'"

HINT="$(request POST "$V/practice/$QUIZ/attempts/$ATTEMPT/hint" '{"level":1}')"
check "hint 1 arrives with two rungs left and gives nothing away" "$HINT" \
  "d['level'] == 1 and d['hints_remaining'] == 2 and d['reveals_solution'] is False"

GRADED="$(request POST "$V/practice/$QUIZ/attempts/$ATTEMPT/submit" "$TWO_CORRECT")"
check "two of five scores 0.4" "$GRADED" "abs(d['score'] - 0.4) < 1e-6"
check "0.4 does not clear the task's 0.8 threshold" "$GRADED" "d['passed'] is False"
check "the hint is recorded on the attempt" "$GRADED" "d['hints_used'] == 1"
check "evidence lands on the concept dimension" "$GRADED" "d['dimension'] == 'concept'"
check "all five questions come back graded" "$GRADED" "len(d['question_results']) == 5"
check "exactly the two answered are correct" "$GRADED" \
  "sum(1 for q in d['question_results'] if q['correct']) == 2"
check "explanations are revealed only now, after grading" "$GRADED" \
  "any(q.get('explanation_md') for q in d['question_results'])"
check "mastery moves on concept for the closures skill" "$GRADED" \
  "any(m['skill_id'] == '$SKILL' and m['dimension'] == 'concept' and m['after'] > m['before'] for m in d['mastery_deltas'])"
printf '       concept delta: %s (hints_used=1; the concept dimension is not discounted by design)\n' \
  "$(value "$GRADED" "next((f\"{m['before']:.4f} -> {m['after']:.4f}\" for m in d['mastery_deltas'] if m['dimension'] == 'concept'), 'none')")"

section "Progress: measured versus unmeasured"
PROGRESS="$(request GET "$V/progress/$SUBJECT")"
check "the closures skill now reports a measured concept dimension" "$PROGRESS" \
  "[s for s in d['skills'] if s['skill_id'] == '$SKILL'][0]['dimensions']['concept']['measured'] is True"
check "no unmeasured dimension carries a nonzero score" "$PROGRESS" \
  "all(dim['score'] == 0.0 for s in d['skills'] for dim in s['dimensions'].values() if dim['measured'] is False)"
check "something is still unmeasured, so the dash path is actually exercised" "$PROGRESS" \
  "any(dim['measured'] is False for s in d['skills'] for dim in s['dimensions'].values())"

section "Quiz: a clean pass"
PERFECT="$(request POST "$V/practice/$QUIZ/attempts/$ATTEMPT/submit" "$ALL_CORRECT")"
check "five of five scores 1.0 and passes" "$PERFECT" \
  "abs(d['score'] - 1.0) < 1e-6 and d['passed'] is True"
check "a pass suggests something to do next" "$PERFECT" "d.get('next') is not None"

section "Sandbox-backed grading"
if [ "$SANDBOX" = "unavailable" ]; then
  ATT="$(request POST "$V/practice/$CODE/attempts")"
  ID="$(value "$ATT" "d['attempt_id']")"
  BODY="$(submission_payload "$TASKS/$CODE.json" code)"
  OUT="$(request POST "$V/practice/$CODE/attempts/$ID/submit" "$BODY")"
  check "with no sandbox, a code submit fails loudly as sandbox_unavailable" "$OUT" \
    "d.get('error', {}).get('code') == 'sandbox_unavailable'"
  skipped "code task grading (no sandbox on this machine; set SANDBOX_MODE=subprocess or build the runner)"
  skipped "debug task grading (same)"
else
  for spec in "$CODE:code:practice" "$DEBUG:debug:debugging"; do
    IFS=: read -r task kind dimension <<< "$spec"
    ATT="$(request POST "$V/practice/$task/attempts")"
    ID="$(value "$ATT" "d['attempt_id']")"
    if [ "$kind" = "debug" ]; then
      request POST "$V/practice/$task/attempts/$ID/hint" '{"level":1}' > /dev/null
      request POST "$V/practice/$task/attempts/$ID/hint" '{"level":2}' > /dev/null
    fi
    BODY="$(submission_payload "$TASKS/$task.json" "$kind")"
    OUT="$(request POST "$V/practice/$task/attempts/$ID/submit" "$BODY")"
    check "$kind: the package's own reference solution passes" "$OUT" "d['passed'] is True"
    check "$kind: evidence lands on the $dimension dimension" "$OUT" "d['dimension'] == '$dimension'"
    check "$kind: the run reports back with tests" "$OUT" \
      "d['execution'] is not None and (d['execution'].get('tests') or d['execution'].get('status') == 'succeeded')"
    check "$kind: mastery moves on $dimension" "$OUT" \
      "any(m['dimension'] == '$dimension' and m['after'] > m['before'] for m in d['mastery_deltas'])"
    if [ "$kind" = "debug" ]; then
      check "debug: both hints are charged to the attempt" "$OUT" "d['hints_used'] == 2"
      printf '       two hints on a doing dimension discount the evidence to 0.70x its raw score\n'
    fi
    printf '       runner reported: %s\n' "$(value "$OUT" "(d.get('execution') or {}).get('runner', 'none')")"
  done

  section "Three dimensions, one skill"
  FINAL="$(request GET "$V/progress/$SUBJECT")"
  check "the closures skill reads as measured on concept, practice and debugging" "$FINAL" \
    "all([s for s in d['skills'] if s['skill_id'] == '$SKILL'][0]['dimensions'].get(x, {}).get('measured') for x in ('concept', 'practice', 'debugging'))"
  check "the three dimensions did not collapse into one number" "$FINAL" \
    "len({round(dim['score'], 6) for k, dim in [s for s in d['skills'] if s['skill_id'] == '$SKILL'][0]['dimensions'].items() if dim['measured']}) > 1"
fi

section "Summary"
printf '  %d passed, %d failed, %d skipped\n' "$PASSED" "$FAILED" "$SKIPPED"
if [ "$FAILED" -gt 0 ]; then
  printf '\n  failed:\n'
  for failure in "${FAILURES[@]}"; do printf '    - %s\n' "$failure"; done
  printf '\n  This is the loop the whole platform exists to run. Fix these before the UI.\n'
  exit 1
fi
if [ "$SKIPPED" -gt 0 ]; then
  printf '  learn -> practice -> grade -> mastery holds, minus %d check(s) this machine could not run.\n' "$SKIPPED"
else
  printf '  learn -> practice -> grade -> mastery holds end to end.\n'
fi
