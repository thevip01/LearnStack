# LearnOS

A learning platform where the *subject* is data, not code.

Most learning platforms grow a branch per subject. A Python course needs a code editor and a
test runner, a cloud course needs a topology diagram, a trading course needs a chart, and
before long the frontend is a switch statement over subject IDs and every new subject means
another release. LearnOS is built the other way round: there is exactly one Subject Runtime,
and a subject is a validated data package that tells the runtime which panels to mount, in
which slots, with which config. Adding a subject means publishing a package. It does not mean
touching the frontend.

That constraint is enforced mechanically rather than by convention. `tools/check_web.py` walks
the import graph and fails the build on any `subject_id ===` comparison, any `switch` over
panel type outside the registry, and any panel component reachable from a server component. As
of this writing the frontend contains zero subject-specific branches.

## Layout

```
apps/api                  FastAPI service, 34 routes, async SQLAlchemy 2.0
apps/web                  Next 15 App Router, React 19, TanStack Query
packages/knowledge-schema  Pydantic models shared by every service, plus the mastery math
services/ingestion        Source to subject-package pipeline (LLM extractor is pluggable)
services/sandbox          Container runner for learner-submitted code
subjects/                 Published subject packages, validated on load
tools/                    Offline verification gates, all stdlib-only
docs/architecture/        Contracts, security model, tiered verification runbook
infrastructure/docker/    Compose stack and per-service images
```

320 files, roughly 50k lines.

## The runtime contract

A subject package declares panels. The runtime renders them. The vocabulary is closed:
30 panel types, 4 slots (`left`, `main`, `right`, `bottom`), and 7 learning modes (`learn`,
`practice`, `lab`, `project`, `production`, `exam`, `review`).

`PANEL_REGISTRY` maps all 30 types to components and is exhaustive by construction, since it
is typed `Record<PanelType, ...>` and TypeScript rejects a missing key. A panel's `config` is
handed to its component untouched and is never interpreted by the layout. Panels with no real
backing source render an honest `NotWired` state that describes the shape they expect, rather
than a fake demo.

The panel set spans code editing and execution (`code_editor`, `file_explorer`, `console`,
`terminal`, `test_results`), data and query work (`sql_console`, `dataset_viewer`, `notebook`),
systems and infrastructure (`architecture_canvas`, `cloud_topology`, `api_client`,
`http_inspector`, `browser_preview`, `incident_console`), and pedagogy
(`curriculum`, `content`, `quiz`, `flashcards`, `hints`, `mastery`, `sources`).

## The mastery model

A skill is scored on six axes rather than one number, because "can explain it" and "can debug
it at 2am" are different claims:

| Dimension | Weight | Measured by |
|---|---|---|
| `concept` | 0.20 | quizzes and checks |
| `practice` | 0.25 | code tasks |
| `lab` | 0.20 | labs |
| `debugging` | 0.15 | debug tasks |
| `production` | 0.10 | production-sizing questions |
| `retention` | 0.10 | spaced review |

Every dimension must be measurable by at least one kind of practice, otherwise it can never be
filled and the overall score is permanently capped. A dimension with no evidence scores `None`,
not zero, so an unmeasured axis is visibly absent instead of silently penalising the learner.

Scores decay on a 90-day half-life with a 0.35 floor. Hints cost 0.15 per level against a 0.40
floor on every dimension except `concept`, where hints are free, since a hint on a
comprehension question is teaching rather than leakage.

## Running it

```bash
make up            # postgres + redis + api + web, no .env file needed
make wait-ready    # blocks until /readyz reports the stack is serving
make reload-subjects
```

Then `http://localhost:3000`. The compose file works on a fresh checkout with no edits.

Two deliberate choices are documented at the top of `docker-compose.yml`: the api container
mounts the host Docker socket so the execution service can launch sandbox containers, which is
root-equivalent access and is acceptable on a laptop and never in production, and `./subjects`
is mounted read-only into the api and read-write into ingestion, since the API consumes subject
packages and only the ingestion build stage may write one.

For a host-native setup with no Docker, `SANDBOX_MODE=subprocess` degrades execution to the
non-containerised path and the practice kinds that need a sandbox skip rather than fail.

## Verification

`make check` is the offline gate and needs no network, no database, and no `node_modules`:

```
compile           every Python file parses
check-imports     132 modules, every intra-repo import resolves to a real symbol
check-web         111 files, imports and named exports resolve, panel registry exhaustive,
                  every route in lib/routes.ts has a page, server/client boundary clean,
                  no subject-specific branching anywhere
check-contract    29 web call sites all map to real API routes; 64 shared models agree
                  field-for-field, with renames and subsets declared explicitly
check-enums       121 modules, no `x is SomeEnum.MEMBER` identity comparisons
validate-nodeps   subject packages validate against the schema
```

Those gates check *names*, not types, so they are a floor and never a substitute for
`tsc --noEmit`. `docs/architecture/11-verification.md` is the tiered runbook: tier 0 is the
offline gates, tier 1 typecheck and build, tier 2 the live stack, tier 3 `make verify-loop`,
which drives a real learn-practice-grade cycle with 31 assertions against real subject IDs.

`packages/knowledge-schema/tests` holds 65 tests covering the mastery math, the hint factors,
decay, the weighted rollup, and enum coercion. They run in well under a second with no
database and no network.

Worth recording, because it is the best argument for writing the suite at all: those tests
immediately found four live bugs sharing one root cause. Pydantic's `use_enum_values=True`
coerces enum fields to `str` at validation time, so every `x is SomeEnum.MEMBER` guard in the
package was silently and permanently false. Because the enums subclass `str`, equality, dict
lookups and f-strings all kept working, and a type checker sees nothing wrong. Four guards were
dead: the hint penalty on `concept`, the weighted score for a successful run with no test
cases, the validator requiring a content hash on a published manifest, and unpublished-package
filtering. `tools/check_enum_identity.py` is now a build gate so the class of bug cannot return.

## Subject packages

A package is a directory of JSON validated against the shared schema, carrying a manifest with
a `content_hash` over the canonicalised content. The hash pins a learner's in-flight work to
the exact version they started on and lets ingestion tell a real content change from a no-op
refresh.

The reference package is `programming.python` v2026.08.0: 10 concepts, 12 skills, 22 practice
tasks, 1 project, 1 assessment, 15 sources. It is deliberately not a beginner tour. The
concepts are the ones that produce production incidents, including mutable default arguments,
late binding in closures, `__eq__` without `__hash__`, and swallowed exceptions, and the
practice tasks are written so that the debug variants require reading a traceback chain rather
than pattern-matching a fix.

## Status

The frontend and the API are feature complete and verified offline, typechecked, and building.
The ingestion pipeline ships with `EXTRACTOR=stub` as the default and no LLM client wired, so
the whole pipeline is runnable and testable on a fresh checkout with no API key. That is not a
placeholder for something missing; it is what makes the pipeline testable at all.

Known gaps: `apps/api/tests` is not written yet, and tier 3 of the runbook has not been run
against a live stack.
