"""Run/Turn boundary schemas."""

from __future__ import annotations

from datetime import datetime

from sul import models
from sul.enums import RunStatus, TurnRole
from sul.schemas.base import ORMModel


class RunCreate(ORMModel):
    study_id: int
    persona_id: int
    scenario_id: int
    status: RunStatus = RunStatus.PENDING

    def to_orm(self) -> models.Run:
        return models.Run(
            study_id=self.study_id,
            persona_id=self.persona_id,
            scenario_id=self.scenario_id,
            status=self.status,
        )


class RunRead(ORMModel):
    id: int
    study_id: int
    persona_id: int
    scenario_id: int
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class TurnCreate(ORMModel):
    run_id: int
    role: TurnRole
    ordinal: int
    content: str
    model_call_id: int | None = None

    def to_orm(self) -> models.Turn:
        return models.Turn(
            run_id=self.run_id,
            role=self.role,
            ordinal=self.ordinal,
            content=self.content,
            model_call_id=self.model_call_id,
        )


class TurnRead(ORMModel):
    id: int
    run_id: int
    role: TurnRole
    ordinal: int
    content: str
    model_call_id: int | None
