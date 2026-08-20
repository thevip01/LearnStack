"""Content addressing for the pipeline.

Every id in this pipeline is derived from content, never from a counter or a UUID.
That is what makes a re-crawl a diff instead of a rebuild: fetch the same page
twice and you get the same ``document_id``, so the second run recognises it as
unchanged and skips parse, chunk, embed and extract for it. With random ids the
pipeline would have no way to tell "this page again" from "a new page", and every
refresh would re-extract the entire source — burning extractor budget and
detaching learner progress from concepts that never actually changed.

The hash is truncated to 40 hex characters. Full SHA-256 is 64, which does not fit
the 80-character columns comfortably once prefixed, and 160 bits is far past the
point where accidental collision matters for a corpus of a few hundred thousand
documents.
"""

from __future__ import annotations

import hashlib
import re

#: Characters that are legal in an ``Id`` segment. Anything else is collapsed.
_UNSAFE = re.compile(r"[^a-z0-9]+")

HASH_LEN = 40


def content_hash(*parts: str | bytes) -> str:
    """Stable hash over the concatenation of ``parts``.

    Parts are length-prefixed before hashing so that ``("ab", "c")`` and
    ``("a", "bc")`` do not collide. Without the prefix, any id built from two
    variable-length fields would have ambiguous boundaries.
    """
    digest = hashlib.sha256()
    for part in parts:
        raw = part.encode("utf-8") if isinstance(part, str) else part
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(b":")
        digest.update(raw)
    return digest.hexdigest()[:HASH_LEN]


def stable_id(prefix: str, *parts: str) -> str:
    """``<prefix>.<hash>`` — a content-derived identifier.

    Used where the id has to be stable across runs but does not have to be
    readable: documents and chunks. Concept and practice ids are authored by
    humans or minted by the extractor and stay readable, because those appear in
    URLs and in hand-maintained JSON.
    """
    return f"{safe_segment(prefix)}.{content_hash(*parts)}"


def document_id_for(source_id: str, locator: str) -> str:
    """Identity of a fetched artefact.

    Keyed on ``(source_id, locator)`` and *not* on the body, because a document's
    identity is where it lives, not what it currently says. The body hash lives in
    ``RawDocument.content_hash``; comparing the two across runs is exactly the
    "changed vs added" distinction ``SourceDiff`` needs. If the id included the
    body, an edited page would look like a new document plus a removed one, and
    every concept derived from it would be orphaned rather than updated.
    """
    return stable_id(f"doc.{source_id}", source_id, locator)


def chunk_id_for(document_id: str, ordinal: int, text: str) -> str:
    """Identity of a retrieval unit.

    Includes the text, unlike ``document_id_for``: a chunk has no independent
    existence to preserve, and including the body means an edit to paragraph nine
    changes chunk nine's id while chunks one through eight keep theirs. That is
    what lets ``diffing`` name the handful of concepts a small edit invalidates
    instead of the whole document's worth.
    """
    return stable_id(f"chunk.{ordinal}", document_id, str(ordinal), text)


def safe_segment(text: str) -> str:
    """Collapse free text into something legal in a dotted ``Id``."""
    lowered = text.strip().lower()
    # Dots are meaningful separators in an Id, so they survive; everything else
    # unsafe collapses to a single hyphen.
    parts = [part for part in lowered.split(".") if part]
    cleaned = [_UNSAFE.sub("-", part).strip("-") for part in parts]
    return ".".join(part for part in cleaned if part) or "x"


def token_estimate(text: str) -> int:
    """Rough token count.

    Four characters per token, the usual English approximation. Deliberately not a
    real tokenizer: this number only decides chunk boundaries and gets logged, and
    pulling in a tokenizer dependency to make a heuristic 8% more accurate is not a
    trade worth making. If a stage ever needs exact counts for a budget, it should
    ask the model provider, not this function.
    """
    return max(1, len(text) // 4)
