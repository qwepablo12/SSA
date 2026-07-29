"""Typed application configuration.

Loaded exactly once, at process startup, and injected from there
(01_Architecture.md §7.5). Application code never reads ``os.environ``: a
setting that is only discovered at the moment it is used is a setting that
fails in production at 03:00 rather than at boot.

Only entrypoints call :meth:`Settings.load` — ``apps/*/main.py``, the Alembic
``env.py``, and the test harness. Everything else receives a ``Settings``
instance through dependency injection.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

__all__ = ["DatabaseSettings", "Environment", "Settings"]


class Environment(StrEnum):
    """Deployment environment. Drives logging format and safety checks."""

    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is Environment.PRODUCTION


class DatabaseSettings(BaseModel):
    """PostgreSQL connection and pool configuration."""

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = "ssa"
    password: SecretStr = SecretStr("")
    name: str = "ssa"

    echo: bool = False
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=5, ge=0)
    pool_timeout_seconds: int = Field(default=10, ge=1)

    @cached_property
    def url(self) -> URL:
        """Connection URL for the asyncpg driver.

        Built with :func:`sqlalchemy.URL.create` rather than string formatting so
        that passwords containing ``@``, ``/`` or ``:`` are escaped correctly —
        hand-built DSNs are a reliable source of "works locally, fails in
        production" connection errors.
        """
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )

    def __str__(self) -> str:
        """Password-free representation, safe to log."""
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.name}"


class Settings(BaseSettings):
    """Root configuration object.

    ``extra="forbid"`` is deliberate: an ``SSA_``-prefixed variable that does not
    map to a field is almost always a typo, and failing loudly beats silently
    running with a default.
    """

    model_config = SettingsConfigDict(
        env_prefix="SSA_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    environment: Environment = Environment.LOCAL
    debug: bool = False

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    test_db: DatabaseSettings | None = None

    @classmethod
    def load(cls) -> Settings:
        """Read configuration from the environment.

        Called only by entrypoints. Raises ``ValidationError`` on a missing or
        malformed value, which is the intended behaviour: fail at boot.
        """
        return cls()
