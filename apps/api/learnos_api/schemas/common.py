"""Shared response primitives.

The contract fixes timestamps as "ISO 8601 with a ``Z`` offset". Pydantic renders
an aware datetime as ``+00:00``, which is the same instant but not the same
string, so every timestamp this API *owns* goes through ``UtcDatetime``.
Timestamps nested inside content models (a concept's ``provenance.generated_at``,
for instance) are serialised by ``learnos_schema`` and render as ``+00:00``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer


def iso_z(value: datetime) -> str:
    """Serialise to ``...Z`` rather than ``...+00:00``.

    Naive datetimes are treated as UTC: everything this service writes is UTC, and
    a naive value in the database means the driver dropped the tzinfo, not that the
    instant is local.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(iso_z, return_type=str, when_used="json")]


class ApiModel(BaseModel):
    """Base for response models.

    ``from_attributes`` lets a response be built straight from an ORM row.
    Unlike ``learnos_schema.SchemaModel`` this does not forbid extras, because
    response models are assembled by this service and never parsed from
    third-party input.
    """

    model_config = ConfigDict(from_attributes=True)
