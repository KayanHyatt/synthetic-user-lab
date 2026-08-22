"""Read-only view models the dashboard renders from -- `sul.web.queries`'
only return types, `extra="forbid"` throughout, the same discipline
`sul.report.model.ReportModel` uses. No ORM object crosses into a template:
a template that needs a new field is a `queries.py` change, not a template
reaching back into a live `Session`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from sul.enums import FindingCategory, RunStatus, TurnRole


class StudyListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: int
    name: str
    artefact_name: str
    created_at: datetime
    run_counts: dict[RunStatus, int]
    total_runs: int


class RunListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int
    persona_name: str
    segment: str
    status: RunStatus
    turn_count: int
    finding_count: int


class TurnView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: int
    role: TurnRole
    ordinal: int
    content: str


class FindingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: int
    category: FindingCategory
    severity: int
    summary: str
    evidence_turn_id: int


class TranscriptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int
    study_id: int
    study_name: str
    persona_name: str
    segment: str
    status: RunStatus
    turns: list[TurnView]
    findings: list[FindingView]


__all__ = [
    "FindingView",
    "RunListItem",
    "StudyListItem",
    "TranscriptView",
    "TurnView",
]
