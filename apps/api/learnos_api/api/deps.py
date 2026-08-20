"""Shared route dependencies.

The registry and the execution service are process-wide singletons created in the
app lifespan and hung off ``app.state``. They are reached through dependencies
rather than imported as module globals so that a test can build an app with a
registry pointed at a fixture directory and a runner that never touches Docker.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_session
from ..errors import InternalError
from ..modules.execution import ExecutionService
from ..modules.subjects import LoadedSubject, SubjectRegistry

# Re-exported so route modules have one import for the common four.
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_registry(request: Request) -> SubjectRegistry:
    registry = getattr(request.app.state, "registry", None)
    if registry is None:  # pragma: no cover - lifespan always sets this
        raise InternalError("subject registry is not initialised")
    return registry


def get_execution(request: Request) -> ExecutionService:
    service = getattr(request.app.state, "execution", None)
    if service is None:  # pragma: no cover - lifespan always sets this
        raise InternalError("execution service is not initialised")
    return service


RegistryDep = Annotated[SubjectRegistry, Depends(get_registry)]
ExecutionDep = Annotated[ExecutionService, Depends(get_execution)]


def resolve_subject(registry: SubjectRegistry, subject_id: str) -> LoadedSubject:
    """Look up a subject, raising the contract's 404 envelope if it is unknown."""
    return registry.get(subject_id)
