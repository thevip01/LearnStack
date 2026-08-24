"""Runtime configuration.

Every value has a default that makes ``docker compose up`` work with no ``.env``
file, because the first thing a new contributor does is run the stack, and a
stack that needs secrets before it will boot does not get run.

The two defaults that are deliberately unsafe, ``JWT_SECRET`` and
``DEMO_USER_PASSWORD``, are checked at startup and refused outside development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SandboxMode = Literal["auto", "docker", "subprocess"]

INSECURE_JWT_SECRET = "dev-insecure-jwt-secret-change-me"


class Settings(BaseSettings):
    """Field names are the env var names, uppercase, one for one."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    API_PORT: int = 8000

    DATABASE_URL: str = "postgresql+asyncpg://learnos:learnos@postgres:5432/learnos"
    REDIS_URL: str = "redis://redis:6379/0"

    JWT_SECRET: str = INSECURE_JWT_SECRET
    JWT_EXPIRES_MINUTES: int = Field(default=60 * 24 * 7, ge=5)

    SUBJECTS_DIR: str = "/app/subjects"

    SANDBOX_MODE: SandboxMode = "auto"
    DOCKER_HOST: str = "unix:///var/run/docker.sock"
    # Name of a Docker network to attach to when a task opts out of
    # ``network: none``. The literal string "none" means "never attach".
    SANDBOX_NETWORK: str = "none"
    EXECUTION_MAX_CONCURRENCY: int = Field(default=4, ge=1, le=64)
    EXECUTION_OUTPUT_LIMIT_BYTES: int = Field(default=64_000, ge=1_024)

    AUTO_CREATE_SCHEMA: bool = True
    SEED_DEMO_USER: bool = True
    DEMO_USER_EMAIL: str = "demo@learnos.dev"
    DEMO_USER_PASSWORD: str = "learnos-demo-2026"

    CORS_ORIGINS: str = "http://localhost:3000"
    OBJECT_STORAGE_DIR: str = "/app/var/objects"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    # ------------------------------------------------------------------
    # Derived
    # ------------------------------------------------------------------

    @property
    def is_development(self) -> bool:
        return self.ENV.lower() in {"development", "dev", "local", "test"}

    @property
    def cookie_secure(self) -> bool:
        """The contract ties ``Secure`` to ``ENV != development``."""
        return not self.is_development

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.CORS_ORIGINS.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def subjects_path(self) -> Path:
        return Path(self.SUBJECTS_DIR)

    @property
    def object_storage_path(self) -> Path:
        return Path(self.OBJECT_STORAGE_DIR)

    @property
    def sandbox_network_enabled(self) -> bool:
        return self.SANDBOX_NETWORK.strip().lower() not in {"", "none"}

    @property
    def alembic_database_url(self) -> str:
        """Alembic's autogenerate runs sync; asyncpg is fine, psycopg is not needed.

        ``env.py`` drives the async engine directly, so this only exists for
        tooling that insists on a URL string.
        """
        return self.DATABASE_URL

    def insecure_defaults(self) -> list[str]:
        """Config that is fine for a laptop and unacceptable anywhere else."""
        problems: list[str] = []
        if self.JWT_SECRET == INSECURE_JWT_SECRET:
            problems.append("JWT_SECRET is still the shipped development default")
        if self.SEED_DEMO_USER:
            problems.append("SEED_DEMO_USER is on, which creates a known-password account")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS is a wildcard")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
