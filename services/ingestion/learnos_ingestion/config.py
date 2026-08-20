"""Ingestion configuration.

Separate from ``learnos_api.config`` on purpose. The two processes share a database
URL and nothing else: the API has a JWT secret and a Docker socket, this has crawl
credentials and an extractor key, and neither should be able to read the other's
environment. A shared settings class would put both sets of secrets in both
processes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    #: Same database the API reads. This service writes ``ingestion_*`` and nothing
    #: else; it must never touch ``users``, ``attempts`` or ``mastery_evidence``.
    database_url: str = Field(
        default="postgresql+asyncpg://learnos:learnos@localhost:5432/learnos",
        alias="DATABASE_URL",
    )

    #: Where subject packages live. Read to discover sources, written by ``build``.
    subjects_dir: Path = Field(default=Path("subjects"), alias="SUBJECTS_DIR")

    #: Raw fetched bytes are written here rather than into a database column.
    #: A crawl of a docs site is tens of megabytes of HTML that nothing queries;
    #: keeping it out of Postgres keeps backups and the diff path cheap.
    storage_dir: Path = Field(default=Path("var/ingestion"), alias="INGESTION_STORAGE_DIR")

    #: Global ceiling, on top of each source's own ``FetchPolicy.rate_limit_rps``.
    #: Present because a run over forty sources that are each politely rate-limited
    #: is still forty concurrent crawls from one IP.
    max_concurrent_fetches: int = Field(default=4, ge=1, le=32, alias="INGESTION_MAX_CONCURRENCY")

    #: ``stub`` produces deterministic candidates with no network call and no key.
    #: It is the default so a fresh checkout can run the whole pipeline offline.
    extractor: str = Field(default="stub", alias="EXTRACTOR")
    extractor_model: str = Field(default="claude-sonnet-4-5", alias="EXTRACTOR_MODEL")
    extractor_api_key: str | None = Field(default=None, alias="EXTRACTOR_API_KEY")

    #: Chunking. 1200 tokens with 120 overlap: large enough that a chunk carries a
    #: whole explanation rather than half of one, small enough to cite precisely.
    chunk_target_tokens: int = Field(default=1200, ge=200, le=8000, alias="CHUNK_TARGET_TOKENS")
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=1000, alias="CHUNK_OVERLAP_TOKENS")

    #: Candidates below this never reach the review queue as ``draft``; they are
    #: written with an ``error`` issue attached so a reviewer sees the extractor
    #: was guessing rather than finding a silently missing concept.
    min_confidence: float = Field(default=0.35, ge=0.0, le=1.0, alias="INGESTION_MIN_CONFIDENCE")

    @field_validator("chunk_overlap_tokens")
    @classmethod
    def _overlap_fits(cls, value: int, info) -> int:  # noqa: ANN001
        target = info.data.get("chunk_target_tokens", 1200)
        if value >= target:
            # Overlap >= target means every chunk contains the whole of the
            # previous one and the chunker never advances. Refuse rather than hang.
            raise ValueError(f"chunk_overlap_tokens ({value}) must be less than chunk_target_tokens ({target})")
        return value

    @property
    def is_development(self) -> bool:
        return self.env.lower() in {"development", "dev", "local"}

    @property
    def raw_dir(self) -> Path:
        return self.storage_dir / "raw"

    def extractor_ready(self) -> tuple[bool, str]:
        """Whether the configured extractor can actually run.

        Returned rather than raised so the CLI can report it in ``--help``-adjacent
        commands and so a ``fetch``-only run is not blocked by a missing key it
        will never use.
        """
        if self.extractor == "stub":
            return True, "stub extractor: deterministic, offline"
        if not self.extractor_api_key:
            return False, f"extractor {self.extractor!r} needs EXTRACTOR_API_KEY"
        return True, f"{self.extractor}:{self.extractor_model}"


@lru_cache
def get_settings() -> IngestionSettings:
    return IngestionSettings()
