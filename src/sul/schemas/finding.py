"""Finding boundary schemas."""

from __future__ import annotations

from pydantic import Field

from sul import models
from sul.enums import FindingCategory
from sul.schemas.base import ORMModel


class FindingCreate(ORMModel):
    run_id: int
    category: FindingCategory
    severity: int = Field(ge=1, le=5)
    summary: str
    evidence_turn_id: int
    cluster_id: int | None = None

    def to_orm(self) -> models.Finding:
        return models.Finding(
            run_id=self.run_id,
            category=self.category,
            severity=self.severity,
            summary=self.summary,
            evidence_turn_id=self.evidence_turn_id,
            cluster_id=self.cluster_id,
        )


class FindingRead(ORMModel):
    id: int
    run_id: int
    category: FindingCategory
    severity: int = Field(ge=1, le=5)
    summary: str
    evidence_turn_id: int
    cluster_id: int | None
