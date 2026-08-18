"""Small shared helpers for the model modules."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time, used as a default for `created_at`-style columns."""
    return datetime.now(UTC)
