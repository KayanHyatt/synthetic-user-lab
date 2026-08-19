"""Application settings, loaded from the environment / `.env`.

M1 deferred `SUL_PROVIDER` and `RECORD` here deliberately ("belong to the
provider abstraction landing in M2"); this is that M2 addition. Provider API
keys are read unprefixed (`ANTHROPIC_API_KEY`, not `SUL_ANTHROPIC_API_KEY`)
via `AliasChoices`, because `.env.example` already documents them that way
and `env_prefix="SUL_"` would otherwise make `Settings` silently ignore them
(`extra="ignore"`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CASSETTE_DIR = Path(__file__).resolve().parents[2] / "tests" / "cassettes"
DEFAULT_PRICING_PATH = Path(__file__).resolve().parents[2] / "configs" / "pricing.yaml"


class Settings(BaseSettings):
    """Process-wide configuration, prefixed `SUL_` in the environment.

    Provider API keys and `RECORD` are the exception — see the module
    docstring — and are read via `AliasChoices` from their unprefixed names.
    """

    model_config = SettingsConfigDict(
        env_prefix="SUL_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///sul.db"
    log_level: str = "INFO"

    # Which provider the runner uses by default: fake | anthropic | openai | gemini
    provider: str = "fake"

    # A study's hard spend ceiling in USD. `BudgetGuard` refuses to dispatch
    # any call that would push spend past this. `None` means unbounded —
    # only appropriate for FakeProvider-only offline runs.
    max_cost_usd: float | None = None

    cassette_dir: Path = DEFAULT_CASSETTE_DIR
    pricing_path: Path = DEFAULT_PRICING_PATH

    # Unprefixed: matches `.env.example`, not `SUL_`-namespaced.
    record: bool = Field(
        default=False, validation_alias=AliasChoices("RECORD", "record")
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "anthropic_api_key"),
    )
    openai_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key")
    )
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "gemini_api_key")
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide cached `Settings` instance.

    Cached (rather than constructed ad hoc at every call site) so every
    consumer agrees on one reading of the environment per process; tests
    that need a different configuration construct `Settings(...)` directly
    instead of going through this accessor.
    """
    return Settings()
