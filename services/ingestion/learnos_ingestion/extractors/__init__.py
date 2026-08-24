"""The extractor contract.

An extractor turns chunks into candidate content. It is a ``Protocol`` rather than a
base class because the two implementations have nothing in common structurally: the
stub is pure computation over text, and an LLM extractor is a network client with
retries and a token budget. What they share is a signature.

**No LLM client ships wired.** ``EXTRACTOR=stub`` is the default, and the stub makes
no network call. This is not a placeholder for something missing: it is what makes
the whole pipeline runnable and testable on a fresh checkout with no key, and it is
what makes the stage boundaries verifiable independently of a model's behaviour. The
LLM path is one file behind an optional dependency; see ``llm.py``.

The contract's important half is the *output*: an extractor returns
``ExtractionCandidate`` objects in ``draft``, each carrying the chunk ids it read
and a confidence. It never returns published content, never writes to the database,
and never decides that something is good enough to show a learner. That decision is
a human's, made through the admin review queue.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from learnos_schema.ingestion import ExtractionCandidate, ExtractionRequest


@runtime_checkable
class Extractor(Protocol):
    """What the extract stage requires of an extractor."""

    #: Goes into ``Provenance.generator`` verbatim, so it must identify the producer
    #: precisely enough to audit: ``"stub:heading-v1"``, ``"llm:claude-sonnet-4-5"``.
    name: str

    async def extract(self, request: ExtractionRequest) -> list[ExtractionCandidate]:
        """Produce candidates for one target from one batch of chunks.

        Must not raise for content reasons. A chunk it cannot make sense of yields
        either no candidate or a low-confidence one with a ``ValidationIssue``
        attached, because an exception would abort the batch and lose the candidates it
        had already produced.
        """
        ...


def resolve(name: str, *, model: str, api_key: str | None) -> Extractor:
    """Build the configured extractor.

    Imports the LLM implementation lazily so that the default path never touches an
    optional dependency, and so a missing ``anthropic`` install produces a clear
    error at the point of configuration rather than an ImportError at module load.
    """
    if name == "stub":
        from .stub import StubExtractor

        return StubExtractor()

    if name == "llm":
        from .llm import LlmExtractor

        return LlmExtractor(model=model, api_key=api_key)

    raise ValueError(f"unknown extractor {name!r}; expected 'stub' or 'llm'")


__all__ = ["Extractor", "resolve"]
