"""Deterministic extractor. No model, no network, no key.

This is not a mock. It produces real, schema-valid candidates by exploiting the
structure the chunker preserved: a heading is a concept name, the prose under it is
the definition and body, a fenced code block is an example, and a paragraph
containing "must", "never" or "always" is a best practice. That is a genuinely
useful first pass over well-structured documentation, and it means a fresh checkout
can run

    learnos-ingest run --subject programming.python --stages fetch,parse,chunk,extract

and get a populated review queue with correct provenance and correct citations,
offline, in about a second.

Everything it emits is built to satisfy the *real* schema models, not a loose
approximation of them. That constraint is the point: a candidate that cannot
validate is a candidate a reviewer can never approve, so an extractor that emits
plausible-looking-but-invalid payloads produces a review queue that is pure cost.
``tests/test_extract_and_build.py`` asserts this against ``Concept`` and
``PracticeTask`` directly, so the two cannot drift apart silently.

What it cannot do is judge. It will not notice that two headings describe the same
idea, it cannot write a question whose distractors are plausible, and it has no view
on whether a concept is worth teaching. Its confidence is capped at 0.55 to say so —
below the 0.6 an operator would reasonably treat as "probably fine", so nothing it
produces looks like it has been vetted.

The value of having it is that every stage boundary downstream — validation, review,
build, the provenance trail — is exercised and testable without a model in the loop.
When the LLM extractor lands, it slots in behind the same Protocol and the stages do
not change.
"""

from __future__ import annotations

import re

from learnos_schema.common import Provenance, SourceRef
from learnos_schema.ingestion import (
    Chunk,
    ExtractionCandidate,
    ExtractionRequest,
    ExtractionTarget,
    ValidationIssue,
)

from ..hashing import content_hash, safe_segment, stable_id

#: Sentences that read as a rule rather than a description. Crude but effective on
#: reference documentation, which is written in exactly this register.
_NORMATIVE = re.compile(
    r"\b(must not|must|should not|should|never|always|required|prohibited|avoid|do not|don't)\b",
    re.IGNORECASE,
)

#: Sentences that explain why a thing exists. Feeds ``Concept.purpose``, which is a
#: required field and the one learners actually retain.
_PURPOSIVE = re.compile(
    r"\b(because|so that|in order to|allows you|allows the|lets you|is used to|useful when|the point is)\b",
    re.IGNORECASE,
)

#: A leading "Foo > Bar" breadcrumb, prepended by the chunker. Stripped before the
#: text becomes prose, since it is navigation rather than content.
_BREADCRUMB = re.compile(r"^[^\n]{0,200}?(?: > [^\n]{0,200}?)+\n\n", re.DOTALL)

_FENCE = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: Nothing this extractor emits goes above this. It has no judgement and the
#: confidence field is where that gets communicated to a reviewer.
MAX_CONFIDENCE = 0.55

#: Languages whose fences are safe to treat as runnable Python. The empty string is
#: included because a bare fence in Python documentation is Python far more often
#: than it is anything else, and the worst case is a reviewer rejecting one task.
_PYTHONISH = frozenset({"python", "py", ""})


class StubExtractor:
    """Structure-driven extraction. Implements the ``Extractor`` protocol."""

    name = "stub:heading-v1"

    async def extract(self, request: ExtractionRequest) -> list[ExtractionCandidate]:
        target = str(request.target)
        if target == ExtractionTarget.CONCEPT.value:
            return self._concepts(request)
        if target == ExtractionTarget.PRACTICE.value:
            return self._practice(request)
        # Curriculum, project and assessment extraction all require judgement about
        # ordering, scope and difficulty that this extractor does not have. Returning
        # nothing is the honest answer; returning a plausible-looking skeleton would
        # put content in the review queue that a reviewer has to read to discover is
        # worthless.
        return []

    # -- concepts -----------------------------------------------------------

    def _concepts(self, request: ExtractionRequest) -> list[ExtractionCandidate]:
        existing = set(request.existing_ids)
        out: list[ExtractionCandidate] = []
        minted: set[str] = set()

        for chunk in request.chunks:
            heading = chunk.heading_path[-1] if chunk.heading_path else None
            if not heading:
                continue

            body = _BREADCRUMB.sub("", chunk.text, count=1).strip()
            prose = self._prose(body)
            if len(prose) < 160:
                continue

            segment = safe_segment(heading)
            concept_id = f"{request.subject_id}.{segment}"
            if concept_id in existing:
                # Already published or already proposed. Emitting a duplicate_of
                # candidate rather than skipping silently, so a reviewer can see the
                # source now says something about a concept that already exists —
                # which is usually a signal the concept needs updating.
                #
                # The payload is a deliberately minimal pointer, not a second copy of
                # the concept: what a reviewer needs here is "look at this one again",
                # and a full payload would invite approving it and clobbering the
                # existing file. It will not validate as a Concept, and the info issue
                # says why, which is the correct outcome for a candidate whose only
                # job is to raise a hand.
                out.append(
                    self._candidate(
                        request,
                        chunk,
                        payload={"id": concept_id, "title": heading},
                        confidence=0.2,
                        duplicate_of=concept_id,
                        issues=[
                            ValidationIssue(
                                severity="info",
                                code="duplicate_concept",
                                message=(
                                    f"{concept_id} already exists; this chunk may contain an update. "
                                    f"Review the existing concept against the cited chunk rather than approving this."
                                ),
                            )
                        ],
                    )
                )
                continue
            if concept_id in minted:
                continue
            minted.add(concept_id)

            reference = SourceRef(
                source_id=chunk.source_id,
                content_hash=chunk.content_hash,
                locator=" > ".join(chunk.heading_path) or None,
                confidence=MAX_CONFIDENCE,
            )
            code_blocks = [
                (language, source.strip()) for language, source in _FENCE.findall(chunk.text) if source.strip()
            ]
            sentences = [sentence.strip() for sentence in _SENTENCE.split(prose) if sentence.strip()]
            practices = [
                sentence for sentence in sentences if _NORMATIVE.search(sentence) and 40 < len(sentence) < 400
            ][:5]
            purpose = next((sentence for sentence in sentences if _PURPOSIVE.search(sentence)), "")

            payload = {
                "id": concept_id,
                "subject_id": request.subject_id,
                "title": heading,
                # The top of the heading path, verbatim. ``category`` is free text
                # shown to humans, so the source's own grouping is a better answer
                # than a slug this extractor invented.
                "category": chunk.heading_path[0] if chunk.heading_path else "general",
                "summary": self._summary(sentences, prose),
                "definition": sentences[0] if sentences else prose[:600],
                "purpose": purpose,
                "body": self._body(prose, code_blocks, reference),
                "best_practices": practices,
                "examples": [
                    {
                        "title": f"Example {index + 1}",
                        "language": language or "text",
                        "code": source,
                    }
                    for index, (language, source) in enumerate(code_blocks[:3])
                ],
                "keywords": [segment, *(safe_segment(part) for part in chunk.heading_path[:2])],
                "estimated_minutes": max(3, min(30, len(prose) // 400 + 3)),
                "sources": [reference.model_dump(mode="json")],
                # Stamped here as well as on the candidate, because the payload is what
                # gets written to disk by the build stage and a concept file with no
                # generator on it is indistinguishable from hand-authored content.
                "provenance": Provenance(generator=self.name).model_dump(mode="json"),
            }

            issues: list[ValidationIssue] = []
            if not payload["examples"]:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="no_examples",
                        message="no code block found in the source chunk; a concept without an example teaches badly",
                        pointer="/examples",
                    )
                )
            if not purpose:
                # Warning rather than error: an empty string satisfies the schema, which
                # is exactly why it needs flagging. A concept that says what something
                # is and never why it exists is the single most common failure of
                # generated learning content.
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="purpose_not_derivable",
                        message=(
                            "no sentence in the source explains why this exists; purpose is empty and must be "
                            "written by a reviewer"
                        ),
                        pointer="/purpose",
                    )
                )
            if not practices:
                issues.append(
                    ValidationIssue(
                        severity="info",
                        code="no_best_practices",
                        message="no normative sentences detected in the source text",
                        pointer="/best_practices",
                    )
                )

            out.append(
                self._candidate(
                    request,
                    chunk,
                    payload=payload,
                    confidence=self._confidence(prose, code_blocks, practices, purpose),
                    issues=issues,
                )
            )

        return out

    # -- practice -----------------------------------------------------------

    def _practice(self, request: ExtractionRequest) -> list[ExtractionCandidate]:
        """One shape only: a single short-answer question over a real code block.

        Modelled as a ``QuizTask`` with one ``short_answer`` question rather than
        anything richer, because every other question type needs authored distractors,
        a hidden test suite or a real traceback, none of which can be derived from
        prose. A multiple-choice question with generated wrong answers is worse than
        no question — a learner who can eliminate three obviously-wrong options learns
        nothing and scores as if they had.
        """
        out: list[ExtractionCandidate] = []

        for chunk in request.chunks:
            for language, source in _FENCE.findall(chunk.text):
                code = source.strip()
                if len(code) < 40 or len(code) > 1200:
                    continue
                if (language or "").lower() not in _PYTHONISH:
                    continue
                if "print(" not in code:
                    # Without a print there is no output to predict, and inventing an
                    # expected value would produce a question with a wrong answer key.
                    continue

                heading = chunk.heading_path[-1] if chunk.heading_path else "this example"
                task_id = f"practice.{request.subject_id}.{content_hash(code)[:12]}"
                reference = SourceRef(
                    source_id=chunk.source_id,
                    content_hash=chunk.content_hash,
                    locator=" > ".join(chunk.heading_path) or None,
                    confidence=MAX_CONFIDENCE,
                ).model_dump(mode="json")
                stem = (
                    f"What does this print?\n\n```python\n{code}\n```\n\n"
                    "Give the exact output, including whitespace."
                )
                payload = {
                    "id": task_id,
                    "subject_id": request.subject_id,
                    "kind": "quiz",
                    "title": f"Predict the output: {heading}",
                    "prompt_md": "Read the code and predict exactly what it prints.",
                    "difficulty": 3,
                    "estimated_minutes": 3,
                    "questions": [
                        {
                            "id": f"{task_id}.q1",
                            "type": "short_answer",
                            "stem_md": stem,
                            "difficulty": 3,
                            "dimension": "concept",
                            # Left empty on purpose. The accepted answers must come
                            # from *running* the code in the sandbox, not from the
                            # extractor's guess. An error issue below keeps the task
                            # out of ``is_promotable`` until a reviewer fills it in, so
                            # it cannot reach a learner unanswerable.
                            "answer": [],
                            "sources": [reference],
                        }
                    ],
                    "evaluation": {"strategy": "exact", "dimension": "concept"},
                    "sources": [reference],
                    "provenance": Provenance(generator=self.name).model_dump(mode="json"),
                }
                out.append(
                    self._candidate(
                        request,
                        chunk,
                        payload=payload,
                        confidence=0.3,
                        issues=[
                            ValidationIssue(
                                severity="error",
                                code="answer_key_empty",
                                message=(
                                    "the accepted answers must be filled from a real sandbox run before approval; "
                                    "the extractor cannot execute code and will not guess"
                                ),
                                pointer="/questions/0/answer",
                            )
                        ],
                    )
                )

        return out

    # -- shared -------------------------------------------------------------

    def _candidate(
        self,
        request: ExtractionRequest,
        chunk: Chunk,
        *,
        payload: dict,
        confidence: float,
        issues: list[ValidationIssue] | None = None,
        duplicate_of: str | None = None,
    ) -> ExtractionCandidate:
        return ExtractionCandidate(
            id=stable_id(f"cand.{request.target}", request.subject_id, str(payload.get("id", "")), chunk.content_hash),
            subject_id=request.subject_id,
            target=request.target,
            payload=payload,
            chunk_ids=[chunk.id],
            confidence=min(confidence, MAX_CONFIDENCE),
            issues=issues or [],
            duplicate_of=duplicate_of,
            provenance=Provenance(generator=self.name),
        )

    @staticmethod
    def _prose(body: str) -> str:
        """Prose only — code fences removed.

        The fences are captured separately as examples and code blocks, and leaving
        them inline would double every code sample in the rendered concept.
        """
        return _FENCE.sub("", body).strip()

    @staticmethod
    def _summary(sentences: list[str], prose: str) -> str:
        """First sentence, hard-capped under the schema's 400-character limit.

        Truncating at 280 rather than 400 leaves room for the reviewer to extend it
        without hitting the ceiling, and a summary longer than a tweet is not a
        summary.
        """
        first = sentences[0].replace("\n", " ") if sentences else prose.replace("\n", " ")
        return first[:280]

    @staticmethod
    def _body(prose: str, code_blocks: list[tuple[str, str]], reference: SourceRef) -> list[dict]:
        """A prose block carrying the citation, then each code sample.

        The citation goes on the prose block rather than only on the concept, because
        the UI renders per-block provenance and a block with no source is rendered as
        unattributed — which for generated content is the wrong claim to make.

        ``runnable`` is false and ``expected_output`` is unset: marking a scraped
        snippet runnable would offer a Run button on code that may not execute in
        isolation, and a failed run in a lesson reads as a broken platform.
        """
        blocks: list[dict] = [
            {"type": "prose", "md": prose, "sources": [reference.model_dump(mode="json")]},
        ]
        for language, source in code_blocks[:3]:
            blocks.append(
                {
                    "type": "code",
                    "runtime": "python" if (language or "").lower() in _PYTHONISH else "none",
                    "language": language or None,
                    "code": source,
                    "runnable": False,
                }
            )
        return blocks

    @staticmethod
    def _confidence(prose: str, code_blocks: list, practices: list, purpose: str) -> float:
        """More structure found means more confidence, capped hard.

        Length alone is weak evidence, so it contributes least; a code block, a
        normative sentence and an explicit why are what distinguish a real reference
        section from a landing page.
        """
        score = 0.25
        if len(prose) > 600:
            score += 0.1
        if code_blocks:
            score += 0.1
        if practices:
            score += 0.05
        if purpose:
            score += 0.05
        return min(score, MAX_CONFIDENCE)
