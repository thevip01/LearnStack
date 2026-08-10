# Verification

This document is how you convince yourself the system works, in the order the
checks get expensive. The cheap ones need nothing installed and run in seconds;
the last one needs Docker and a few minutes of clicking. Run them in order,
because a failure in an early tier explains most failures in a later one.

---

## Tier 0: nothing installed

```
make check
```

Six targets, no dependencies, no network, no imports of the code under test:

- `compile`: every Python file parses.
- `check-imports` (`tools/check_imports.py`): every intra-repo import resolves to
  a name the target module really binds, and `__all__` never exports something
  that was deleted.
- `check-web` (`tools/check_web.py`): the frontend equivalent. Every `@/…` and
  relative import resolves, every *named* import is really exported, every
  `Record<PanelType, …>` map is exhaustive, every route in `lib/routes.ts` has a
  page under `app/`, no module branches on a specific subject id, and no React
  hook is called in a module reachable from a server entry without crossing a
  `"use client"` boundary.
- `check-contract` (`tools/check_contract.py`): every `apiFetch` path in the web
  app resolves to a real FastAPI route, and every model shared by both sides has
  the same field names. Request models are checked directionally: the frontend
  may omit a field with a server-side default, but not a required one.
- `check-enums` (`tools/check_enum_identity.py`): no `x is SomeEnum.MEMBER`
  outside the enum class's own body. `SchemaModel` sets `use_enum_values=True`, so
  an enum-typed field holds a plain `str` once validated, and because every enum
  here subclasses `str` only `is` stops matching. It stops matching silently and
  always, which turns a guard into a no-op that reads correctly and type-checks
  clean. Four of them were dead at once; tier 1 has the list.
- `validate-nodeps`: the stdlib subject-package validator.

**What tier 0 cannot tell you.** It checks names, not types. It does not know
whether a value is a `string` or a `number`, whether a component's props line up,
or whether the layout a subject declares actually renders. A green `make check`
with a broken `tsc` is entirely possible.

## Tier 1: typecheck and build

```
make test-web       # tsc --noEmit && next build
make test           # pytest, for the suites that exist
```

`tsc` is the real gate for the frontend and needs `npm install` first. Neither
target can run in an environment without a package registry, which is the whole
reason tier 0 exists.

`make test` is still thinner than it looks. `packages/knowledge-schema/tests` and
`services/ingestion/tests` are written; `test-api` prints `no suite yet` and
passes, because a target that exits non-zero on a directory nobody has created yet
trains people to stop running it. That honesty is the point, not a licence to
leave it, so see Known gaps.

`packages/knowledge-schema/tests` is 65 tests over the arithmetic, and it needs
only `pytest` and `pydantic`: no database, no network, no fixtures on disk except
the one subject package the repo ships. It pins the hint penalty factors and their
`0.40` floor, hints being free on `concept` and costly everywhere else, the 90-day
evidence half-life and the `0.35` recency floor, `compute_dimension_score([])`
returning `None` rather than a zero, the weighted rollup and its `coverage` share,
the five mastery states, and the logistic ability update with its clamps.

Worth knowing what happened the first time it ran, because it is the argument for
writing these at all. Four invariants turned out to be dead, all from the same
cause: `x is SomeEnum.MEMBER` against a field that `use_enum_values=True` had
already coerced to a `str`.

1. `apply_hint_penalty` charged hints on the `concept` dimension. A quiz taken with
   two hints landed evidence at `0.70 ×` its score instead of the documented full
   credit.
2. `ExecutionResult.weighted_score` returned `0.0` for every successful run that
   carried no test cases, which is every task graded on "it ran and printed the
   right thing".
3. The "a published manifest must carry a `content_hash`" validator never fired,
   so the guard existed only in the source.
4. `load_all_packages(..., skip_unpublished=True)` dropped every package including
   the published ones, and returned an empty catalogue without raising.

None of the four raised, and a type checker is happy with all of them, which is
why the fix shipped with `check-enums` rather than four one-line diffs.
`tests/test_enum_coercion.py` asserts the root cause directly and keeps
`ExecutionStatus.is_terminal` as the blessed counter-example, since identity on
`self` inside the enum's own body is sound.

## Tier 2: the stack comes up

```
make up             # builds the runner image, starts postgres, redis, api, web
make wait-ready     # blocks until /readyz answers
```

`/readyz` reports each dependency separately but returns 503 for one reason only:
Postgres is down. Redis down means slower responses, sandbox down means
execution-backed panels degrade, and neither is a reason to pull the instance out
of rotation, so both surface as `status: "degraded"` with 200. This matters here
because `make wait-ready` polls that route: when it 503'd on a missing runner
image, `make up` failed on a stack that was serving correctly. The web app renders
the same state as a banner from `useReady()` and never gates the UI on it, so if
the banner is absent while the API says degraded, the banner is broken, not the
API.

### When `make up` dies during a build

Read the failure before believing it. BuildKit reports a failed base-image pull
against the *next* instruction, because it cannot compute that step's cache key
until the `FROM` layers exist. So this:

```
 => ERROR [2/4] RUN pip install --no-cache-dir "pytest==8.3.2" ...      0.0s
Dockerfile:27
ERROR: failed to solve: failed to compute cache key: failed to copy:
       local error: tls: bad record MAC
```

is not a broken pip line. The tells are the `0.0s` and, a few lines up, the pull
still sitting at `0B / 30.14MB`. `bad record MAC` means the TLS stream got
corrupted in transit, which is a fault in the Docker VM's networking rather than
anything in this repo. It is size-dependent and intermittent: small responses
almost always land, multi-megabyte ones sometimes do not, so retrying is a real
strategy and not superstition.

On Colima, cheapest first:

```bash
# 0. Colima ships neither plugin, and `make up` needs compose. This is a
#    prerequisite, not a fix for the error above.
brew install docker-buildx docker-compose

# 1. Shrink the MTU. Fixes most corruption-on-large-transfer cases.
colima ssh -- sudo ip link set dev eth0 mtu 1400

# 2. Still failing? Recreate the VM on Apple's own hypervisor.
colima delete -f
colima start --vm-type=vz --mount-type=virtiofs --mount $HOME:w \
  --cpu 4 --memory 6 --disk 40

# 3. Pull the base images up front, with retries, so the builds start warm.
for image in python:3.12-slim node:22-alpine pgvector/pgvector:pg16 redis:7-alpine; do
  for attempt in 1 2 3 4 5; do docker pull "$image" && break; sleep 3; done
done
```

Step 3 helps but does not finish the job: `apps/api` pip-installs and `apps/web`
runs `npm ci` inside their own builds, and a `RUN` layer that dies partway restarts
from zero rather than resuming.

No Docker, or a machine that cannot run it? `SANDBOX_MODE=subprocess` runs
submissions in a local subprocess instead. It logs
`sandbox.mode mode=subprocess isolation=weak` on the way up, and that warning is
accurate: it is fine for verifying the loop on your own machine and unacceptable
anywhere untrusted code can reach it.

Demo account, development only: `demo@learnos.dev` / `learnos-demo-2026`. It is
seeded idempotently and `SEED_DEMO_USER` is refused outside development.

## Tier 3: the loop

This is the one that matters, because it is the only tier that exercises
learn → practice → grade → mastery as a single path. The subject package in the
repo is `programming.python`, so every id below is real and can be pasted.

Everything in this tier that can be asserted, is:

```
make verify-loop    # tools/verify_loop.sh
```

That script walks the whole path against the running stack and checks 34
invariants: the scores, the thresholds, the hint asymmetry, the idempotent
attempt, the dash-not-zero rule, and the three dimensions refusing to collapse.
The code and debug submissions are read out of the subject package on disk, so a
pass means the grader graded a real reference solution rather than a fixture
agreeing with itself. It exits 2 if the stack is not usable, 1 on a failed
invariant, and skips (rather than fails) the two sandbox-backed checks when the
machine has no sandbox, because a missing Docker is a fact about the machine and
not a defect in the code. Read the browser walkthrough below anyway: the script
cannot see the UI, and half of these rules are about what a learner is shown.

**In the browser** (`http://localhost:3000`):

1. `/subjects` lists domains with subject cards. A subject you have never touched
   shows its provider, not a 0% bar. That is the honest-empty-state rule, not a
   missing feature.
2. Open Python. The overview shows version, content hash on hover, mode tiles
   built from `runtime.modes`, and any recommendations with the reason string the
   recommender composed. A mode the package declares but does not lay out is
   visible and disabled, never hidden.
3. Enter `learn`. The workspace mounts the generic runtime: `mode_layouts.learn`
   decides the slots, `PANEL_REGISTRY` resolves each `panel.type`, and the
   navigation tree comes from `runtime.navigation`. Nothing in that path knows it
   is rendering Python.
4. Switch to `practice`. Pick `python.practice.closures.check.late-binding`, a
   five-question quiz whose `evaluation.dimension` is `concept` and whose
   `pass_threshold` is `0.8`, so four of five correct passes and three does not.
   Take a hint on the way through; level 3 is marked `reveals_solution: true`, so
   it should be presented as the last one and it gives the answers away.
5. Submit. The result panel renders `feedback_md`, per-question correctness with
   each question's `explanation_md` (never before grading), and `mastery_deltas`
   with the before and after score for the dimension the task carried.
6. Open `/progress/programming.python`. The skill
   `python.skill.reason-about-closures` should now show movement on `concept`, and
   **a dash on every dimension with no evidence yet**. A zero there is a bug: it
   tells a learner who has done the reading that they failed the labs they have
   not attempted.
7. Now the other two tasks on that same skill, which is the part worth doing
   deliberately: `python.practice.closures.code.counter-factory` carries
   `practice`, and `python.practice.closures.debug.late-binding-loop` carries
   `debugging`. Both run pytest in the sandbox at `pass_threshold: 1.0`. After all
   three, one skill should read three separately measured dimensions, which is the
   whole mastery model in one screen, and if the three collapse into a single
   number the rollup is wrong.
8. With the sandbox down, step 7 is where it must fail loudly: a
   `sandbox_unavailable` error, not a spinner that never resolves.

**The hint asymmetry is worth checking explicitly**, because it is the rule most
likely to be broken by a well-meaning refactor. `apply_hint_penalty` charges
`0.15` per hint level against the evidence score, floored at `0.40`, and charges
**nothing** on the `concept` dimension. Reading an explanation while learning a
definition is fine; being walked through a debugging session is not evidence you
can debug. So: hints on the quiz should leave the delta untouched, and two hints
on the debug task should land evidence at `0.70 ×` its raw score. Both are visible
in `mastery_deltas`, and both are pinned in
`packages/knowledge-schema/tests/test_mastery.py`, which is the cheaper place to
notice a regression.

**As curl**, if you want to drive one step at a time instead of running the script.
Login sets an httpOnly cookie *and* returns the token, so a jar is enough:

```bash
API=http://localhost:8000/api/v1
JAR=/tmp/learnos.jar

curl -sS -c $JAR -X POST $API/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"demo@learnos.dev","password":"learnos-demo-2026"}' | python3 -m json.tool

TASK=python.practice.closures.check.late-binding
ATTEMPT=$(curl -sS -b $JAR -X POST $API/practice/$TASK/attempts \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["attempt_id"])')

# Optional: take a hint. On a concept-dimension task this must not cost anything.
curl -sS -b $JAR -X POST $API/practice/$TASK/attempts/$ATTEMPT/hint \
  -H 'content-type: application/json' -d '{"level":1}' | python3 -m json.tool

curl -sS -b $JAR -X POST $API/practice/$TASK/attempts/$ATTEMPT/submit \
  -H 'content-type: application/json' \
  -d '{"kind":"quiz","answers":{"closures.the-classic-loop":"a","closures.default-arg-capture":"a"}}' \
  | python3 -m json.tool

curl -sS -b $JAR "$API/progress/programming.python" | python3 -m json.tool
```

Expected: two of five right is `score: 0.4`, `passed: false` against the `0.8`
threshold, `hints_used: 1`, and a `mastery_deltas` entry on `concept` that the
hint did **not** discount. Re-running `attempts` returns the same `attempt_id`
rather than opening a second one, because it is idempotent on purpose: a learner
who reloads the page must not lose the hints they have already paid for.

The submission response carries `mastery_deltas`; the progress response should
show the same numbers. If the delta is non-zero and progress has not moved, the
evidence write and the rollup have diverged, which is a backend bug and not
something the UI can paper over.

---

## Known gaps

These are deliberate, and a reviewer should not read them as breakage:

- **`apps/api/tests` does not exist.** `packages/knowledge-schema/tests` and
  `services/ingestion/tests` are real; the API layer has no suite yet, and
  `make test` says so out loud instead of failing. What is missing is the route
  level: auth and the cookie, attempt idempotency, and the submit-to-evidence-to-
  rollup path end to end. `tools/verify_loop.sh` covers that ground against a
  running stack, so it is a stand-in, not a replacement, and it needs Docker and a
  seeded database to say anything at all.
- Five API routes have no caller in the web app yet: `GET
  /admin/ingestion/runs/{id}`, `POST /admin/ingestion/sources`, `GET
  /admin/subjects/{id}/validate`, `POST /admin/subjects/reload`, and `GET
  /healthz`. `check-contract` lists them on every run so the gap stays visible.
- Five panel types render a `NotWired` state describing the shape they will take:
  tutor, notebook, metrics, trading and simulation. No endpoint backs them, and
  faking one would be worse than saying so.
- `DimensionScore` on the frontend reads `score` and `measured` only. The wire
  carries evidence counts too; nothing renders them yet.
