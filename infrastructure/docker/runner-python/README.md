# Sandbox runner images

One image per runtime. Right now there is exactly one — `learnos/runner-python:3.12`
— and adding a second should feel like a deliberate act, because each image is a
new attack surface that runs hostile code.

The execution service picks an image from `DEFAULT_RUNTIME_IMAGES` in
`apps/api/learnos_api/modules/subjects/registry.py`, keyed by the
`SandboxLimits.runtime` / `runtime_version` a task declares. A subject package
cannot name an arbitrary image; if the runtime is unknown, the submission is
rejected rather than run somewhere unexpected.

## Why versions are pinned

Three separate reasons, and any one of them is sufficient:

1. **Grading is a measurement.** A learner's mastery score is evidence recorded
   permanently in an append-only table. If `pytest` silently updates and changes
   how a report is shaped, or Python 3.12.4 changes a stdlib behaviour a test
   depends on, then two learners who wrote identical code get different scores
   and the older evidence is no longer comparable to the newer. Pinning is what
   makes "you scored 0.8 on this task" mean the same thing in March and in
   November.
2. **Content is authored against a specific runtime.** A subject package's tasks,
   expected outputs and error-message examples are written by a human running a
   particular interpreter. `common_errors[].error` strings in concepts are matched
   against real tracebacks by search; those strings change between versions.
3. **A sandbox image must be reviewable.** An unpinned image is a different image
   tomorrow. You cannot say "we audited what is installed" about a moving target,
   and the whole argument for the network and capability restrictions rests on
   knowing exactly what binaries are present.

The base image uses the `python:3.12-slim` tag rather than a digest, which is a
deliberate compromise: patch-level security updates land on rebuild, while the
language version — the thing content is authored against — cannot move. Python
packages inside the image are pinned exactly, because those are the ones that
decide pass or fail. If you need reproducibility down to the byte, pin the base
by digest and accept that you now own the CVE cadence.

## Adding a runtime

1. Create `infrastructure/docker/runner-<name>/Dockerfile`. Copy the flag
   discipline from `runner-python`: non-root user, a single owned workspace
   directory, no network tools, no compiler unless the subject genuinely needs
   one, nothing installed that is not used.
2. Install the *minimum* test tooling and pin it exactly.
3. Add the image to `DEFAULT_RUNTIME_IMAGES` with its default command.
4. Add it as a build-only service in the root `docker-compose.yml` under the
   `images` profile, and to the `runner` target in the `Makefile`.
5. If the runtime's test output is not pytest's, add a harness beside
   `services/sandbox/learnos_sandbox/harness/pytest_harness.py` that emits the
   same JSON payload behind the same `__LEARNOS_RESULT_V1__` sentinel. The Docker
   runner is runtime-agnostic: it packs a workspace, runs a command, and parses
   one line. Keeping that true is what stops "add JavaScript support" from
   turning into a second execution pipeline.
6. Read `services/sandbox/README.md` before you do any of this. Every container
   flag there applies to the new image too, and the reasons are listed.

## Verifying an image by hand

```sh
docker build -t learnos/runner-python:3.12 infrastructure/docker/runner-python
docker run --rm learnos/runner-python:3.12                 # prints versions
docker run --rm --network none --read-only \
  --tmpfs /workspace:size=64m --user nobody --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 64 --memory 256m \
  learnos/runner-python:3.12 python -c "print('locked down and still working')"
```

The second command is the shape the execution service uses. If it fails, the
image needs fixing, not the flags.
