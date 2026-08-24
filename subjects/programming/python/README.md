# Python: LearnOS subject package

This directory is a **subject package**: a self-contained, validated bundle of
JSON that fully describes a subject to LearnOS. There is no Python-specific
application code anywhere in the platform. The generic Subject Runtime reads
this directory, and everything a learner sees (the curriculum, the reading,
the practice, the sandbox, the assessment, the mastery model) is produced from
the data below. This package is the reference implementation of that idea, and
the proof that *the subject is data*.

If you want to add a subject, you copy this shape and change the contents. You
do not write a new app.

## What this package teaches

Core Python for a working engineer, organised around the failure modes that
actually show up in tracebacks. One track (`python.core`), four modules, ten
concepts, twelve skills, and a capstone build:

| Module | Concepts | The idea |
| --- | --- | --- |
| Foundations | objects & names, control flow & truthiness, sequences & mappings | Names are bindings, not boxes. Aliasing, mutable defaults and dict keys all fall out of that one fact. |
| Functions and Scope | signatures, closures & late binding, decorators | A signature is an API contract; closures are how Python remembers, and late binding is how it surprises you. |
| Data Modelling | comprehensions, classes & dunders | Build collections declaratively, then build your own types that behave like the built-in ones. |
| Correctness and Performance | exceptions, complexity | Errors are part of your API, and so is the complexity of the loop you just wrote. The project and the checkpoint live here. |

The capstone is `python.project.lru-cache`: build a fixed-capacity LRU cache
whose `get` and `put` are both O(1), then prove it under a large workload. The
module checkpoint, `python.assessment.core`, measures three mastery
dimensions (concept, debugging, production) before it will report mastery.

## Layout

```
programming/python/
├── manifest.json      # identity, version, runtimes, dimension weights, content_hash
├── ui.json            # which panels render in each mode (learn/practice/lab/project/exam/review)
├── curriculum.json    # tracks → modules → concepts, and the 12 skills with dimension weights
├── sources.json       # the 15 registered sources; every citation must resolve to one of these
├── concepts/          # 10 concept documents (the reading)
├── practice/          # 22 practice tasks (quizzes, code, debug)
├── projects/          # 1 project (the LRU cache capstone)
├── assessments/       # 1 assessment (the module checkpoint)
└── labs/              # (none yet, labs are optional long-form guided builds)
```

Every file is keyed by a dotted **id** (e.g. `python.exceptions`,
`python.practice.decorators.code.retry`). Ids are how the parts reference each
other: a concept lists the practice tasks that reinforce it, a skill lists the
concepts that teach it, an assessment section lists the practice it draws from.
The validator checks that every reference resolves.

## The practice set

Twenty-two tasks, spanning three kinds and all six question types:

- **10 quizzes**: multiple-choice, multi-select, fill-in-the-blank, ordering,
  matching and short-answer questions. Correct answers live only in the
  `answer` field and are stripped before anything reaches a learner.
- **6 code tasks**: write code against a hidden test suite in the sandbox
  (dedupe preserving order, a keyword-only config normaliser, a closure-based
  counter factory, a `functools.wraps` retry decorator, and two labs: copy
  semantics and a `@total_ordering` Money value type).
- **6 debug tasks**: a broken program plus a symptom; find and fix the root
  cause (shared mutable default, late-binding loop, a decorator that erases
  metadata, a swallowed exception, an unhashable dict key, and reading a
  chained traceback to its origin).

Every task carries a three-level hint ladder where only the last hint reveals a
solution, and every task's `provenance` records who generated it, who reviewed
it, and its lifecycle status.

## Mastery is multi-dimensional

A learner does not have a single "Python score". Each of the twelve skills
declares `dimension_weights` across six axes (concept, practice, lab,
debugging, production, retention) and a skill's mastery is only as complete as
the dimensions that are actually *measured* by some practice task. The
validator enforces this: if a skill weights the `debugging` dimension but no
practice task measures debugging for that skill, that is an **error**, not a
warning, because the skill's mastery would be silently capped. This is why the
practice set is shaped the way it is: the debug tasks exist to make the
debugging dimension reachable for the skills that claim it.

## Validating the package

The stdlib validator is dependency-free (no pydantic, no third-party packages)
and mirrors the schema exactly by introspecting it:

```bash
python3 subjects/validate_package.py subjects/programming/python
```

A clean run prints:

```
OK   programming.python v2026.08.0 (10 concepts, 12 skills, 22 practice, 1 projects, 1 assessments, 15 sources)
```

If you have the schema package installed (`make install`), the richer
Pydantic-based validator additionally runs soft lint checks and prints the
authoritative content hash:

```bash
learnos-validate check subjects/programming/python --strict
```

## The content hash / build step

A published manifest must carry a real `content_hash`; a placeholder fails
validation. The hash pins a learner's in-flight work to the exact package
version they started on and lets ingestion tell a real content change from a
no-op refresh. Stamp it with:

```bash
python3 tools/build_content_hash.py subjects/programming/python
```

The tool has two modes and picks automatically. When `learnos_schema` is
importable it writes the **authoritative** hash:
`SubjectPackage.compute_content_hash()`, a sha256 over the fully-validated,
default-filled model dump with the volatile manifest fields excluded. In a
minimal checkout with no dependencies it falls back to a **stdlib** hash over
the canonicalised JSON files, which is stable and non-placeholder, enough to
publish and to pin a version. Re-run it once dependencies are installed to
converge on the canonical value. Use `--check` in CI to fail a build whose
manifest hash is stale.

## Rules a contributor should know

These are enforced by the validator, so you will find out quickly, but knowing
them up front saves a round trip:

- **`extra = "forbid"` everywhere.** An unknown key is a hard error. Do not
  invent fields; if a value has nowhere to go, it does not belong.
- **Citations must resolve.** Every `source_id` in any `sources` list must be
  one of the 15 ids registered in `sources.json`.
- **Ids must be unique and referenced ids must exist.** Concepts, skills,
  practice, projects and assessments all live in one id namespace.
- **Answers and hidden tests are secrets.** Correct answers, hidden test
  bodies, solution files, and debug root causes are stripped by the `sanitized`
  path and never reach a learner before they pass.
- **One runtime.** The manifest declares a single `python` runtime at version
  `3.12`; every code/debug task's `environment.runtime` must match.
- **Provenance is mandatory on published content.** Nothing is published
  without a `provenance` block naming its generator and reviewer.

To extend the subject, add a JSON file under the right directory, wire its id
into the concept/skill/module that should reference it, re-run the validator
until it prints `OK`, and re-stamp the content hash. No code changes required:
that is the whole point.
