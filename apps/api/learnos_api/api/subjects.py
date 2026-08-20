"""Subject runtime, concepts, graph, readiness and recommendations.

Five reads that together are everything the learning shell needs. Three notes on
the shape of them:

* **The runtime payload is assembled once, at load.** This router attaches the
  learner's ``progress`` block to the cached object and returns it; it never
  re-derives layouts or navigation. That is what makes the heaviest endpoint in
  the product cheap enough to call on every page.
* **Every route is auth-optional.** Anonymous callers get the same content with
  ``progress: null`` and no prerequisite warnings, because a subject nobody can
  read without an account is a subject nobody chooses to study.
* **Opening a lesson writes.** ``GET .../concepts/{id}`` logs a
  ``concept_viewed`` event for a signed-in learner. A GET with a side effect is a
  deliberate trade: the alternative is a second request the frontend must
  remember to send, and a view count that silently undercounts is worse than a
  non-idempotent read of an activity log.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..modules import knowledge, practice, progress
from ..modules.auth.deps import OptionalUser
from ..modules.progress import rollup
from ..schemas.concept import ConceptOut
from ..schemas.graph import GraphOut, ReadinessOut, RecommendationsOut
from ..schemas.subject import SubjectRuntimeOut
from .deps import RegistryDep, SessionDep, resolve_subject

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.get("/{subject_id}", response_model=SubjectRuntimeOut)
async def subject_runtime(
    subject_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: OptionalUser,
) -> SubjectRuntimeOut:
    subject = resolve_subject(registry, subject_id)
    if user is None:
        return subject.runtime

    learner_progress = await rollup.get_progress(session, user_id=user.id, package=subject.package)
    # A copy, not a mutation: ``subject.runtime`` is the shared object every other
    # request is served from, and writing one learner's progress onto it would hand
    # it to the next caller.
    return subject.runtime.model_copy(update={"progress": learner_progress})


@router.get("/{subject_id}/concepts/{concept_id}", response_model=ConceptOut)
async def concept(
    subject_id: str,
    concept_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: OptionalUser,
) -> ConceptOut:
    subject = resolve_subject(registry, subject_id)
    concept_model = registry.concept(subject_id, concept_id)

    stats = None
    masteries = None
    if user is not None:
        stats = await practice.attempt_stats(session, user_id=user.id, subject_id=subject_id)
        masteries = await rollup.mastery_lookup(
            session, user_id=user.id, subject_id=subject_id, package=subject.package
        )
        await progress.log_concept_view(session, user_id=user.id, subject_id=subject_id, concept_id=concept_id)

    return knowledge.concept_out(subject=subject, concept=concept_model, stats=stats, masteries=masteries)


@router.get("/{subject_id}/graph", response_model=GraphOut)
async def graph(
    subject_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: OptionalUser,
    include: str = Query("all", pattern="^(all|concepts|skills)$"),
) -> GraphOut:
    subject = resolve_subject(registry, subject_id)
    masteries = None
    if user is not None:
        masteries = await rollup.mastery_lookup(
            session, user_id=user.id, subject_id=subject_id, package=subject.package
        )
    return knowledge.graph.build(subject.package, masteries=masteries, include=include)


@router.get("/{subject_id}/readiness", response_model=ReadinessOut)
async def readiness(
    subject_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: OptionalUser,
    skill_id: str = Query(min_length=1),
) -> ReadinessOut:
    subject = resolve_subject(registry, subject_id)
    # Resolve first so an unknown skill is a 404 rather than a cheerful "ready".
    registry.skill(subject_id, skill_id)
    masteries: dict = {}
    if user is not None:
        masteries = await rollup.mastery_lookup(
            session, user_id=user.id, subject_id=subject_id, package=subject.package
        )
    return knowledge.readiness_for_skill(subject.package, skill_id, masteries)


@router.get("/{subject_id}/next", response_model=RecommendationsOut)
async def next_actions(
    subject_id: str,
    registry: RegistryDep,
    session: SessionDep,
    user: OptionalUser,
    limit: int = Query(5, ge=1, le=20),
) -> RecommendationsOut:
    subject = resolve_subject(registry, subject_id)
    view = await progress.learner_view(
        session, user_id=user.id if user else None, package=subject.package
    )
    return progress.recommend(
        subject.package,
        concept_order=subject.concept_order,
        view=view,
        limit=limit,
    )
