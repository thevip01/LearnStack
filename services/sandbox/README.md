# LearnOS sandbox

Running code a stranger wrote is the single most dangerous thing this platform
does. This directory holds the contract for doing it: the `Runner` protocol, the
workspace packer, and the harness that runs inside the container. The two runner
implementations live in the API (`apps/api/learnos_api/modules/execution/`)
because they need the application's settings and logging; everything they agree
on lives here.

## Threat model

The attacker is an authenticated learner who can submit arbitrary source files
and an arbitrary run command for the task's declared runtime. Assume they are
hostile and competent. What they must not be able to do:

| Goal | Why it matters |
| --- | --- |
| Read or write host files | Other learners' submissions, `.env`, the Docker socket |
| Reach the network | Exfiltrating secrets, using the box as a proxy, DDoS from your IP |
| Reach Postgres, Redis, or the API | Rewriting their own mastery, reading other accounts |
| Stay alive after the timeout | Compute cost, and a queue that never drains |
| Exhaust host memory or CPU | Takes down the API for everyone |
| Fork-bomb | Same, and hard to clean up |
| Escalate to root on the host | Total compromise |
| Extract hidden test bodies or expected answers | Destroys the assessment |
| Flood the response with output | Memory pressure in the API process |

What is explicitly *out* of scope: a container escape through a kernel bug. The
defence there is that a sandbox host runs nothing else valuable, and in
production the sandbox is a separate machine — not the box holding the database.

## What each Docker flag defends against

The runner launches every container with all of the following. None of them are
optional and none of them are decoration.

- **No bind mounts, ever.** The workspace is copied in with `put_archive`. A
  bind mount is a writable hole in the host filesystem, and the usual mistakes
  (mounting a parent directory, a symlink inside the mount escaping it, mount
  propagation) all end in host file access. Copying costs a few milliseconds for
  a few kilobytes of source.
- **`network_disabled=True`** unless the task's `SandboxLimits.network` opts in.
  Removes exfiltration, dependency installation at runtime, and any route to
  Postgres/Redis/the API — which are all reachable by hostname from a container
  on the compose network. This is the single highest-value flag.
- **`read_only=True`** on the root filesystem, plus a small `tmpfs` at
  `/workspace`. The learner can write where they are supposed to and nowhere
  else: no editing `/etc`, no dropping a binary in `/usr/local/bin`, no
  persisting anything into the image layer.
- **`tmpfs` with `size=`, `noexec` where possible.** A writable directory with no
  size limit is a way to consume host memory (tmpfs is RAM) without tripping the
  memory limit.
- **`user="nobody"`** (uid 65534). Even if something in the image is misconfigured
  as root-writable, an unprivileged uid cannot use it. The runner image also
  defines a non-root default user; this flag means we do not have to trust that.
- **`cap_drop=["ALL"]`** removes every Linux capability. No `CAP_NET_RAW` (raw
  sockets), no `CAP_SYS_ADMIN` (mount), no `CAP_CHOWN`, no `CAP_DAC_OVERRIDE`.
  Nothing a test runner does needs one.
- **`security_opt=["no-new-privileges"]`** stops a setuid binary inside the image
  from regaining privilege after we dropped it. Without this, `cap_drop` is a
  speed bump.
- **`mem_limit`** with swap pinned to the same value, so the container cannot
  swap its way past the limit. Exceeding it is an OOM kill, which the runner
  reports as `oom` rather than a mysterious failure — telling a learner "your
  solution used too much memory" is a real lesson.
- **`nano_cpus`** caps CPU share. A busy loop then costs a fraction of a core
  instead of starving the API's event loop.
- **`pids_limit`** caps process count, which is the direct answer to a fork bomb.
  It is set from the task's limits, defaulting low.
- **`container.wait(timeout=...)` then `kill()`.** The timeout is enforced from
  outside, because a limit the sandboxed process enforces on itself is not a
  limit. Timeout, OOM (exit 137 with `State.OOMKilled`) and ordinary non-zero
  exits are distinguished, since they mean different things to the learner.
- **Output cap** at `EXECUTION_OUTPUT_LIMIT_BYTES` with a `truncated` flag.
  `while True: print("x")` must not turn into unbounded memory growth in the API
  process or a gigabyte in the response body.
- **Concurrency semaphore** at `EXECUTION_MAX_CONCURRENCY`. Bounds total sandbox
  memory and CPU regardless of how many learners submit at once.
- **`auto_remove` / explicit removal in a `finally`.** A leaked container is a
  leaked resource limit.
- **Docker SDK calls wrapped in `asyncio.to_thread`.** The SDK is synchronous;
  calling it directly from a coroutine blocks the event loop and makes one slow
  submission look like an outage.

## Keeping the answers hidden

Isolation is only half the job. The other half is that pytest prints the source
of a failing assertion, so raw pytest output *is* the answer key for a hidden
test. Hence `harness/pytest_harness.py`:

1. It captures everything pytest writes and emits exactly one line of JSON
   behind the `__LEARNOS_RESULT_V1__` sentinel.
2. When a test manifest is present (i.e. there are authored tests, some possibly
   hidden), the captured terminal output is **not included in the payload at
   all** — not truncated, not redacted, absent.
3. The API's code grader then builds `TestResult` objects and, for any test whose
   `TestCase.visible` is false, keeps only the test's *name* — never the body,
   the assertion text, the traceback, or the expected value.
4. `learnos_sandbox.protocol.unpack_result` strips every sentinel line from the
   stdout it returns, so a learner who prints the sentinel themselves cannot
   confuse the client and cannot see their own forged line echoed back.

The invariant to hold onto: **the only path from a task definition to a client is
the model's `sanitized()` method**, and the only path from a test run to a client
is the grader's redaction step. If you add a code path that reaches around
either, you have created the bug this directory exists to prevent.

## Development fallback

`SubprocessRunner` exists so that `make dev-api` works on a laptop with no Docker.
It uses `resource.setrlimit` for CPU, address space, file size and process count,
runs in a temporary directory as the API's own user, and logs a loud warning at
startup. It is **not** a security boundary: same uid, same filesystem, same
network. `SANDBOX_MODE=subprocess` is a development convenience and the API says
so every time it starts.

`/readyz` reports which one is live (`"sandbox": "docker" | "subprocess" |
"unavailable"`), so this is never a silent downgrade.

## Adding a runtime

1. Add an image under `infrastructure/docker/runner-python`'s sibling directory
   and pin it (see that README).
2. Register it in `DEFAULT_RUNTIME_IMAGES` in
   `apps/api/learnos_api/modules/subjects/registry.py`.
3. If its test output is not pytest's, write a harness beside
   `pytest_harness.py` that emits the same payload shape behind the same
   sentinel. The runner does not need to change: it packs a workspace, runs a
   command, and parses one JSON line.
