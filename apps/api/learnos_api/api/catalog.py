"""The catalogue: every loaded subject, grouped by domain.

Served entirely from the registry's in-memory dictionaries plus one aggregate
query for the signed-in learner's numbers. No package file is read here, and no
per-subject rollup is computed — see ``rollup.catalog_snapshot`` for why the cards
read a cache while the progress page does not.
"""

from __future__ import annotations

from ..modules.auth.deps import OptionalUser
from ..modules.progress import rollup
from ..modules.subjects import assemble
from ..schemas.catalog import CatalogDomainOut, CatalogOut, CatalogProgressOut, CatalogSubjectOut
from fastapi import APIRouter

from .deps import RegistryDep, SessionDep

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=CatalogOut)
async def catalog(registry: RegistryDep, session: SessionDep, user: OptionalUser) -> CatalogOut:
    snapshot = await rollup.catalog_snapshot(session, user_id=user.id) if user else {}

    grouped: dict[str, CatalogDomainOut] = {}
    for subject in registry.all_subjects():
        package = subject.package
        domain = package.manifest.domain
        bucket = grouped.get(domain.id)
        if bucket is None:
            bucket = CatalogDomainOut(id=domain.id, title=domain.title, icon=domain.icon)
            grouped[domain.id] = bucket

        card: CatalogSubjectOut = assemble.catalog_subject(package)
        if user is not None:
            overall, mastered = snapshot.get(package.id, (0.0, 0))
            card = card.model_copy(
                update={
                    "progress": CatalogProgressOut(
                        overall=overall,
                        skills_mastered=mastered,
                        skills_total=len(package.curriculum.skills),
                    )
                }
            )
        bucket.subjects.append(card)

    # Domains in manifest-declared order would be arbitrary across packages, so
    # they are sorted by title; subjects inside a domain keep the registry's
    # (domain, title) ordering.
    return CatalogOut(domains=sorted(grouped.values(), key=lambda item: item.title))
