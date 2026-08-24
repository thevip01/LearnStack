"""Ad-hoc execution.

This is the "run the snippet in the lesson" endpoint, and it is the most abusable
surface in the product: it spends real CPU on request. Three controls sit on it,
all here rather than in the service, because the service is also used by grading
where the limits come from the authored task instead:

1. **Authentication is required.** Anonymous code execution is a free compute
   endpoint on the public internet.
2. **Rate limited per user**, not per IP: the cost is per account, and an IP is
   shared by everyone behind one NAT.
3. **The caller's limits are ignored.** The contract is explicit: an ad-hoc run
   always gets the tightest defaults. Memory, CPU, process count and network are
   not expressible in the request body at all, so a snippet in a lesson cannot ask
   for the network: "the client asked nicely" is not a basis for granting it. Only
   the timeout is negotiable, and only up to a ceiling.

Runs whose declared timeout is under ``INLINE_TIMEOUT_LIMIT_S`` are answered
inline with 200. Anything longer returns 202 and a pollable id.
"""

from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Response, status
from learnos_schema import ExecutionRequest, ExecutionResult, SandboxLimits, SourceFile
from pydantic import BaseModel, Field

from ..errors import NotFound
from ..modules.auth import ratelimit
from ..modules.auth.deps import CurrentUser
from ..schemas.health import ExecutionQueuedOut
from ..schemas.practice import SubmittedFile
from .deps import ExecutionDep, SessionDep

router = APIRouter(prefix="/execution", tags=["execution"])

#: The only limits an ad-hoc run may have. Not merged with anything the caller
#: sends: a merge is a place for a field to slip through.
ADHOC_LIMITS = SandboxLimits(
    runtime="python",  # type: ignore[arg-type]
    timeout_s=5,
    memory_mb=256,
    cpu_limit=0.5,
    network="none",
    pids_limit=32,
)


class AdhocRunIn(BaseModel):
    """A snippet to run.

    ``runtime`` names a *kind* ("python"), never an image. The registry maps the
    kind to a pinned image, so "run this in ``attacker/evil:latest``" is not
    expressible in this API.
    """

    runtime: str = Field(default="python", max_length=40)
    runtime_version: str | None = Field(default=None, max_length=20)
    files: list[SubmittedFile] = Field(min_length=1, max_length=32)
    command: str | None = Field(default=None, max_length=500)
    stdin: str | None = Field(default=None, max_length=64_000)
    #: Used to pick the inline-versus-queued path, clamped to
    #: ``ADHOC_TIMEOUT_CEILING_S``. It is the only limit the caller may influence.
    timeout_s: int = Field(default=5, ge=1, le=120)


#: The one limit a caller may raise. Time is the only ad-hoc knob that does not
#: weaken isolation (memory, CPU, pids and network stay pinned at the defaults
#: above), and a lesson that demonstrates a slow loop needs it. Raising it moves
#: the run onto the queued path, so a long request never holds a worker open.
ADHOC_TIMEOUT_CEILING_S = 60


def _request_for(body: AdhocRunIn) -> ExecutionRequest:
    limits = ADHOC_LIMITS.model_copy(
        update={
            "runtime": body.runtime,
            "runtime_version": body.runtime_version,
            "timeout_s": min(max(body.timeout_s, 1), ADHOC_TIMEOUT_CEILING_S),
        }
    )
    return ExecutionRequest(
        files=[SourceFile(path=file.path, content=file.content) for file in body.files],
        command=body.command,
        stdin=body.stdin,
        limits=limits,
    )


@router.post("/runs", response_model=Union[ExecutionResult, ExecutionQueuedOut])
async def create_run(
    body: AdhocRunIn,
    response: Response,
    execution: ExecutionDep,
    session: SessionDep,
    user: CurrentUser,
) -> ExecutionResult | ExecutionQueuedOut:
    await ratelimit.enforce(ratelimit.ADHOC_EXECUTION_LIMIT, str(user.id))
    request = _request_for(body)

    if not execution.should_run_inline(request):
        execution_id = await execution.enqueue(request, user_id=user.id)
        response.status_code = status.HTTP_202_ACCEPTED
        return ExecutionQueuedOut(execution_id=execution_id)

    outcome = await execution.execute(request)
    await execution.record(
        session,
        outcome.result,
        user_id=user.id,
        runtime=str(request.limits.runtime),
    )
    return outcome.result


@router.get("/runs/{execution_id}", response_model=ExecutionResult)
async def get_run(
    execution_id: str,
    execution: ExecutionDep,
    session: SessionDep,
    user: CurrentUser,
) -> ExecutionResult:
    result = await execution.load(session, execution_id, user_id=user.id)
    if result is None:
        # Deliberately the same 404 for "no such run" and "not yours". Telling a
        # caller that a run exists but belongs to somebody else is an enumeration
        # oracle over other learners' work.
        raise NotFound("no such execution")
    return result
