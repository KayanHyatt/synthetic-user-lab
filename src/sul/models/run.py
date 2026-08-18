"""Run and Turn: one persona's pass through one scenario, and its transcript.

`Run` + its ordered `Turn` rows *are* the transcript — there is no separate
Session/Transcript table (see docs/architecture.md for why).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sul.enums import RunStatus, TurnRole
from sul.models.base import Base

if TYPE_CHECKING:
    from sul.models.finding import Finding
    from sul.models.panel import Persona
    from sul.models.study import Scenario, Study
    from sul.models.telemetry import ModelCall


class Run(Base):
    """One persona's pass through one scenario within a study.

    The unique `(study_id, persona_id, scenario_id)` triple is what lets the
    M4 orchestrator resume a killed study without creating duplicate runs:
    re-running simply upserts against this key instead of blindly inserting.
    """

    __tablename__ = "runs"
    __table_args__ = (sa.UniqueConstraint("study_id", "persona_id", "scenario_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(
        sa.ForeignKey("studies.id", ondelete="CASCADE"), index=True
    )
    persona_id: Mapped[int] = mapped_column(
        sa.ForeignKey("personas.id", ondelete="CASCADE"), index=True
    )
    scenario_id: Mapped[int] = mapped_column(
        sa.ForeignKey("scenarios.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        sa.Enum(
            RunStatus, native_enum=False, values_callable=lambda e: [m.value for m in e]
        ),
        default=RunStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime, default=None)
    error: Mapped[str | None] = mapped_column(sa.Text, default=None)

    study: Mapped[Study] = relationship(back_populates="runs")
    persona: Mapped[Persona] = relationship(back_populates="runs")
    scenario: Mapped[Scenario] = relationship(back_populates="runs")
    turns: Mapped[list[Turn]] = relationship(
        back_populates="run",
        order_by="Turn.ordinal",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings: Mapped[list[Finding]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    model_calls: Mapped[list[ModelCall]] = relationship(back_populates="run")

    def __repr__(self) -> str:
        return (
            f"Run(id={self.id!r}, study_id={self.study_id!r}, status={self.status!r})"
        )


class Turn(Base):
    """One utterance in a run's transcript, ordered by `ordinal`."""

    __tablename__ = "turns"
    __table_args__ = (sa.UniqueConstraint("run_id", "ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[TurnRole] = mapped_column(
        sa.Enum(
            TurnRole, native_enum=False, values_callable=lambda e: [m.value for m in e]
        )
    )
    ordinal: Mapped[int] = mapped_column(sa.Integer)
    content: Mapped[str] = mapped_column(sa.Text)
    model_call_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("model_calls.id", ondelete="SET NULL"), default=None
    )

    run: Mapped[Run] = relationship(back_populates="turns")
    model_call: Mapped[ModelCall | None] = relationship(back_populates="turns")

    def __repr__(self) -> str:
        return f"Turn(id={self.id!r}, run_id={self.run_id!r}, ordinal={self.ordinal!r})"
