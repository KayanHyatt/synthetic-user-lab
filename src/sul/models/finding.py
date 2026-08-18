"""Finding: a structured observation extracted from a completed transcript.

`evidence_turn_id` is NOT NULL by design: a finding with no evidence is
exactly what M5's "every finding links to at least one transcript turn"
acceptance test exists to catch, so it is rejected at the schema level rather
than left to the report renderer to notice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sul.enums import FindingCategory
from sul.models.base import Base

if TYPE_CHECKING:
    from sul.models.run import Run, Turn


class Finding(Base):
    """One structured, evidence-linked observation emitted by the Analyst."""

    __tablename__ = "findings"
    __table_args__ = (
        sa.CheckConstraint("severity BETWEEN 1 AND 5", name="severity_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[FindingCategory] = mapped_column(
        sa.Enum(
            FindingCategory,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    severity: Mapped[int] = mapped_column(sa.Integer)
    summary: Mapped[str] = mapped_column(sa.Text)
    evidence_turn_id: Mapped[int] = mapped_column(
        sa.ForeignKey("turns.id", ondelete="CASCADE"), index=True
    )
    cluster_id: Mapped[int | None] = mapped_column(sa.Integer, default=None)

    run: Mapped[Run] = relationship(back_populates="findings")
    evidence_turn: Mapped[Turn] = relationship(foreign_keys=[evidence_turn_id])

    def __repr__(self) -> str:
        return f"Finding(id={self.id!r}, category={self.category!r})"
