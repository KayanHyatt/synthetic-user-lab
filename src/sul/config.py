"""Application settings, loaded from the environment / `.env`.

Only the fields M1 needs. `SUL_PROVIDER` and `RECORD` (see `.env.example`)
belong to the provider abstraction landing in M2 and are intentionally not
modelled here yet.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration, prefixed `SUL_` in the environment."""

    model_config = SettingsConfigDict(
        env_prefix="SUL_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///sul.db"
    log_level: str = "INFO"
