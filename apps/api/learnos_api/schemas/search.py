"""Search envelope."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ApiModel

SearchKind = Literal["concept", "practice", "project", "skill", "subject"]
MatchedOn = Literal["title", "keyword", "body", "error_text"]


class SearchResultOut(ApiModel):
    id: str
    kind: SearchKind
    subject_id: str
    title: str
    snippet: str
    score: float
    #: Which field carried the match. ``error_text`` is the interesting one: it
    #: means the learner pasted an error and we found the concept that explains it,
    #: and the UI labels that result differently.
    matched_on: MatchedOn


class SearchOut(ApiModel):
    query: str
    results: list[SearchResultOut] = Field(default_factory=list)
