"""Enumerations shared by the ORM models and the Pydantic schemas.

Kept in one module, imported by both `sul.models` and `sul.schemas`, so the
two layers never need to duplicate — or drift on — a set of allowed values.
"""

from __future__ import annotations

import enum


class ArtefactKind(enum.StrEnum):
    """The shape of a product artefact shown to a persona."""

    HTML = "html"
    TEXT = "text"
    IMAGE = "image"


class RunStatus(enum.StrEnum):
    """Lifecycle of a single persona x scenario run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TurnRole(enum.StrEnum):
    """Who spoke in a transcript turn.

    Deliberately excludes "analyst": the Analyst reads completed transcripts
    and emits Findings, but never writes a Turn.
    """

    MODERATOR = "moderator"
    PERSONA = "persona"


class AgentRole(enum.StrEnum):
    """Which agent triggered a ModelCall.

    A superset of TurnRole, because ModelCall must also account for Analyst
    calls (which produce Findings, not Turns) so that cost queries such as
    `sul cost <study_id>` are complete.
    """

    MODERATOR = "moderator"
    PERSONA = "persona"
    ANALYST = "analyst"


class FindingCategory(enum.StrEnum):
    """Fixed taxonomy an Analyst classifies Findings into (spec §M4)."""

    BLOCKER = "blocker"
    CONFUSION = "confusion"
    MISSING_INFO = "missing_info"
    TRUST = "trust"
    PRICING = "pricing"
    DELIGHT = "delight"
