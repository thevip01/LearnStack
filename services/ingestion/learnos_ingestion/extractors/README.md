# Extractors

An extractor turns chunks of source text into candidate content. It is the one place
in LearnOS where a language model is allowed near learner-visible material, and the
rules below are what keep that safe.

Two ship in the box:

| name   | network | key | confidence ceiling | what it is for |
|--------|---------|-----|--------------------|----------------|
| `stub` | no      | no  | 0.55               | the default; proves the pipeline offline |
| `llm`  | yes     | yes | 0.75               | complete except the model call |

`EXTRACTOR=stub` is the default so that a fresh checkout can run
`fetch -> parse -> chunk -> extract -> validate` with no account, no key and no
budget. Everything downstream of extraction — validation, review, build — is
exercised identically by both, which is the point: the review queue you empty
against the stub is the same review queue you will empty against a real model.

## The three rules

**The model never invents a source.** Citations are built by the extractor's own code
from the chunk ids that went into the prompt. A model asked to cite its sources will
produce plausible ones, and a plausible citation in a learning platform is worse than
none: a learner who follows it lands on a page that does not say what the concept
claims, and concludes the platform is lying — which, at that point, it is.

**The model never sets its own confidence.** `_confidence()` computes it from
properties of the output that can be checked without trusting the model: whether the
explanation is substantial, whether a code sample parses, whether the payload
validated, how many chunks backed it. A self-reported confidence is a number the
model chose to make its answer look good.

**Output is capped below the review threshold regardless.** Neither extractor can
emit a candidate that looks vetted. Nothing generated reaches a learner without a
human setting `approved`, and the ceiling exists so that no amount of prompt
engineering can make generated content *appear* to have cleared that bar.

## Adding one

Implement the `Extractor` protocol — a `name` and an `async extract(request)` — and
register it in `resolve()`. Two contract points are easy to miss:

- **Do not raise for content reasons.** A chunk that yields nothing returns an empty
  list. An exception aborts the batch and loses the candidates already produced in
  it, so a single unparseable page costs eight chunks' worth of work.
- **`name` is written verbatim into `Provenance.generator`.** It ends up in the audit
  trail for every candidate, so make it specific enough to answer "which version of
  which extractor produced this?" six months later — `llm:claude-sonnet-4-5`, not
  `llm`.

## Wiring the LLM extractor

```bash
pip install -e 'services/ingestion[llm]'
export EXTRACTOR=llm
export EXTRACTOR_API_KEY=...          # never committed; not in .env.example
export EXTRACTOR_MODEL=claude-sonnet-4-5
```

`llm.py` is complete apart from the provider call itself: prompt construction,
response normalisation, citation assembly, confidence computation and issue reporting
are all there and all tested against recorded payloads. The single `TODO` is the
request. `temperature=0.0` is set and should stay there — a run that cannot be
reproduced cannot be reviewed.

`_normalise()` discards keys the schema does not declare rather than passing them
through. Every schema model sets `extra="forbid"`, so an unexpected key would fail
validation not here but at build time, long after a reviewer approved the candidate —
the worst possible moment to discover it.

## What is deliberately absent

No embedding provider (see `stages/chunk.py:run_embed` — retrieval runs on Postgres
full-text and trigram search, which is sufficient at this corpus size). No automatic
approval, at any confidence, ever. No extractor call anywhere in the API process: the
request path must never depend on a third-party model being up.
