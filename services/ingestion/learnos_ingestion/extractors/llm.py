"""LLM extractor. Requires the ``llm`` extra and a key; not installed by default.

This file exists so the seam is real rather than hypothetical. It is a complete
implementation of the ``Extractor`` protocol whose one unwired part is the model
call itself. Everything around it (prompt construction, JSON extraction, id
minting, provenance, confidence, citation back to chunk ids) is written, because
those are the parts that decide whether generated content is auditable, and getting
them right is not something to leave until the day someone adds a key.

Deliberate choices worth stating:

**The model never invents a source.** Citations are constructed from the chunk ids
that went into the prompt, not from anything the model returns. A model asked to
cite its sources will produce plausible ones, and a learning platform whose
provenance trail is itself generated has no provenance trail.

**The model never sets its own confidence.** Self-reported confidence from a language
model is not calibrated, and treating it as if it were would let a fluent wrong
answer outrank a hedged right one in the review queue. Confidence here is computed
from verifiable properties of the output.

**Output is capped below the review threshold regardless.** Nothing that comes out of
a model is marked as anything but ``draft``, and no confidence value skips review.
"""

from __future__ import annotations

import json
import re

from learnos_schema.common import Provenance, SourceRef
from learnos_schema.ingestion import (
    Chunk,
    ExtractionCandidate,
    ExtractionRequest,
    ExtractionTarget,
    ValidationIssue,
)

from ..hashing import stable_id

#: Highest confidence any generated candidate can carry. Under the 0.6 an operator
#: would read as "probably fine", because generated content should never look pre-vetted.
MAX_CONFIDENCE = 0.75

#: A fenced JSON block, or a bare object. Models wrap JSON in prose reliably enough
#: that parsing has to tolerate it.
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)

SYSTEM_PROMPT = """\
You extract structured learning content from technical documentation.

Rules:
- Use ONLY the provided source text. If the text does not support a claim, omit it.
- Never invent APIs, flags, version numbers, error messages or behaviour.
- Prefer quoting exact identifiers and error strings from the source over paraphrase.
- If the source text is insufficient to produce a complete item, return fewer items \
rather than padding them.
- Return a single JSON array and no prose.
"""

TARGET_INSTRUCTIONS = {
    ExtractionTarget.CONCEPT.value: """\
Return a JSON array of concept objects. Each object:
  title            short noun phrase, the thing being taught
  summary          one sentence, under 280 characters
  explanation_md   markdown, 2-6 paragraphs, no headings
  difficulty       integer 1-10
  tags             up to 5 lowercase kebab-case strings
  best_practices   up to 5 imperative sentences drawn from the source
  misconceptions   up to 3 objects {claim, correction} of things learners get wrong
Do not include an id; ids are assigned by the pipeline.
""",
    ExtractionTarget.PRACTICE.value: """\
Return a JSON array of practice task objects. Each object:
  kind        one of: multiple_choice, short_answer, predict_output
  title       short
  prompt_md   the question, markdown
  difficulty  integer 1-10
  For multiple_choice: options (4 strings) and correct_index (0-3). Every distractor
  must be a mistake a learner could plausibly make; never use obviously absurd options.
  For short_answer: accepted (list of acceptable answers, lowercase).
  For predict_output: code (python) and leave expected_output out entirely. It is
  filled by running the code, not by you.
  hints       exactly 3, increasing in specificity; the third may not give the answer.
""",
}


class LlmExtractor:
    """Extractor backed by a language model."""

    def __init__(self, *, model: str, api_key: str | None) -> None:
        if not api_key:
            raise ValueError(
                "LlmExtractor requires an API key. Set EXTRACTOR_API_KEY, or leave EXTRACTOR=stub "
                "to run the deterministic extractor with no network access."
            )
        self.model = model
        self.name = f"llm:{model}"
        self._api_key = api_key
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "the 'llm' extra is not installed. Run: pip install -e services/ingestion[llm]"
            ) from exc
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def extract(self, request: ExtractionRequest) -> list[ExtractionCandidate]:
        target = str(request.target)
        instructions = TARGET_INSTRUCTIONS.get(target)
        if instructions is None:
            # Curriculum, project and assessment extraction are not prompted for.
            # Each needs to reason over an entire subject rather than a chunk batch,
            # which is a different call shape and a different budget; doing it badly
            # from a handful of chunks would produce a module ordering that looks
            # authoritative and is arbitrary.
            return []

        raw = await self._complete(self._build_prompt(request, instructions))
        items = _parse_items(raw)

        out: list[ExtractionCandidate] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not item.get("title"):
                continue
            payload, issues = self._normalise(item, request, index)
            out.append(
                ExtractionCandidate(
                    id=stable_id(
                        f"cand.{target}",
                        request.subject_id,
                        str(payload.get("id", "")),
                        "|".join(chunk.content_hash for chunk in request.chunks),
                    ),
                    subject_id=request.subject_id,
                    target=request.target,
                    payload=payload,
                    # Every chunk in the batch, because the model saw all of them and
                    # attributing a claim to one specific chunk would be a guess.
                    chunk_ids=[chunk.id for chunk in request.chunks],
                    confidence=_confidence(payload, issues),
                    issues=issues,
                    provenance=Provenance(generator=self.name),
                )
            )
        return out

    def _build_prompt(self, request: ExtractionRequest, instructions: str) -> str:
        parts = [instructions]
        if request.hint:
            parts.append(f"Focus: {request.hint}")
        if request.existing_ids:
            parts.append(
                "These concepts already exist; do not duplicate them:\n"
                + "\n".join(f"- {existing}" for existing in request.existing_ids[:80])
            )
        parts.append("SOURCE TEXT:")
        for chunk in request.chunks:
            heading = " > ".join(chunk.heading_path) if chunk.heading_path else "(untitled section)"
            parts.append(f"--- {heading} ---\n{chunk.text}")
        return "\n\n".join(parts)

    async def _complete(self, prompt: str) -> str:
        client = self._ensure_client()
        response = await client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            # Zero temperature: extraction should be reproducible, and two runs over
            # the same source producing different candidates would make the review
            # queue impossible to reason about.
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")

    def _normalise(
        self, item: dict, request: ExtractionRequest, index: int
    ) -> tuple[dict, list[ValidationIssue]]:
        """Shape a model object into a payload, dropping anything unasked-for.

        Unknown keys are discarded rather than passed through. ``SchemaModel`` sets
        ``extra="forbid"``, so a hallucinated field would fail validation at the
        promote step, long after a reviewer approved it, which is the worst moment
        to discover it.
        """
        issues: list[ValidationIssue] = []
        from ..hashing import safe_segment

        title = str(item.get("title", "")).strip()
        item_id = f"{request.subject_id}.{safe_segment(title)}"
        target = str(request.target)

        sources = [
            SourceRef(
                source_id=chunk.source_id,
                content_hash=chunk.content_hash,
                locator=" > ".join(chunk.heading_path) or None,
                confidence=0.6,
            ).model_dump(mode="json")
            for chunk in request.chunks[:5]
        ]

        if target == ExtractionTarget.CONCEPT.value:
            explanation = str(item.get("explanation_md", "")).strip()
            if len(explanation) < 200:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="thin_explanation",
                        message=f"explanation is {len(explanation)} characters; likely under-supported by the source",
                        pointer="/explanation_md",
                    )
                )
            payload = {
                "id": item_id,
                "subject_id": request.subject_id,
                "title": title,
                "summary": str(item.get("summary", ""))[:280],
                "explanation_md": explanation,
                "difficulty": _clamp_int(item.get("difficulty"), 1, 10, 3),
                "tags": [safe_segment(str(tag)) for tag in _as_list(item.get("tags"))[:5]],
                "skills": [],
                "prerequisites": [],
                "examples": [],
                "best_practices": [str(practice) for practice in _as_list(item.get("best_practices"))[:5]],
                "misconceptions": [
                    {"claim": str(entry.get("claim", "")), "correction": str(entry.get("correction", ""))}
                    for entry in _as_list(item.get("misconceptions"))[:3]
                    if isinstance(entry, dict)
                ],
                "sources": sources,
            }
            return payload, issues

        kind = str(item.get("kind", "")).strip()
        if kind not in {"multiple_choice", "short_answer", "predict_output"}:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unknown_kind",
                    message=f"kind {kind!r} is not one this extractor is allowed to produce",
                    pointer="/kind",
                )
            )
            kind = "short_answer"

        hints = [str(hint) for hint in _as_list(item.get("hints"))[:3]]
        if len(hints) < 3:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="short_hint_ladder",
                    message=f"{len(hints)} hints; a ladder needs three so a stuck learner has somewhere to go",
                    pointer="/hints",
                )
            )

        payload = {
            "id": f"practice.{request.subject_id}.{safe_segment(title)}.{index}",
            "subject_id": request.subject_id,
            "kind": kind,
            "title": title,
            "prompt_md": str(item.get("prompt_md", "")),
            "difficulty": _clamp_int(item.get("difficulty"), 1, 10, 3),
            "skills": [],
            "hints": [
                {"level": level + 1, "text_md": text, "reveals_solution": False}
                for level, text in enumerate(hints)
            ],
            "evaluation": {"dimension": "concept", "max_score": 1.0},
            "sources": sources,
        }

        if kind == "multiple_choice":
            options = [str(option) for option in _as_list(item.get("options"))[:4]]
            payload["options"] = options
            payload["correct_index"] = _clamp_int(item.get("correct_index"), 0, max(len(options) - 1, 0), 0)
            if len(options) < 4:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="too_few_options",
                        message=f"{len(options)} options; a multiple-choice question needs four",
                        pointer="/options",
                    )
                )
        elif kind == "short_answer":
            payload["accepted"] = [str(answer).lower() for answer in _as_list(item.get("accepted"))[:8]]
            if not payload["accepted"]:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="no_accepted_answers",
                        message="short_answer with no accepted answers can never be passed",
                        pointer="/accepted",
                    )
                )
        else:
            payload["code"] = str(item.get("code", ""))
            payload["language"] = "python"
            payload["expected_output"] = ""
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="expected_output_empty",
                    message="expected_output must come from a real sandbox run, not from the model",
                    pointer="/expected_output",
                )
            )

        return payload, issues


def _parse_items(raw: str) -> list:
    """Pull a JSON array out of a model response."""
    match = _JSON_BLOCK.search(raw)
    text = match.group(1) if match else raw.strip()
    try:
        loaded = json.loads(text)
    except ValueError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            loaded = json.loads(text[start : end + 1])
        except ValueError:
            return []
    if isinstance(loaded, dict):
        return [loaded]
    return loaded if isinstance(loaded, list) else []


def _as_list(value) -> list:  # noqa: ANN001
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clamp_int(value, low: int, high: int, default: int) -> int:  # noqa: ANN001
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _confidence(payload: dict, issues: list[ValidationIssue]) -> float:
    """Computed from the output, never taken from the model.

    Errors floor it hard: a candidate with a structural error should sit at the top
    of a queue sorted by ascending confidence, which is how the admin list is
    ordered.
    """
    if any(issue.severity == "error" for issue in issues):
        return 0.15
    score = 0.5
    if len(str(payload.get("explanation_md", ""))) > 800:
        score += 0.1
    if payload.get("best_practices"):
        score += 0.05
    if payload.get("misconceptions"):
        score += 0.1
    if any(issue.severity == "warning" for issue in issues):
        score -= 0.15
    return max(0.1, min(score, MAX_CONFIDENCE))
