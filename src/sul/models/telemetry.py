"""ModelCall: the row every LLM call writes, regardless of which agent made it.

This is what makes cost and reproducibility auditable (spec §M1) — nothing
calls an LLM yet in M1, this just creates the row M2's provider abstraction
will write into.

`run_id` is nullable and `agent` records who made the call, because the
Analyst produces `ModelCall` rows that have no corresponding `Turn` (the
Analyst never writes a transcript turn — see `sul.enums.TurnRole` vs
`sul.enums.AgentRole`). Without `run_id` here, `sul cost <study_id>` (M2's
acceptance criterion) would silently miss Analyst spend.

> **M4 implementation note.** `template_version` (nullable) was added beyond
> M1's table. The §M4 carry-forward requires "whatever identifies the
> template version is recorded with the call" — nothing on `ModelCall` could
> carry that before this milestone actually rendered a prompt from a file.
> Folding it into `prompt_hash` would record it unreadably (a hash cannot be
> read back out); a dedicated column keeps it queryable per M1's own
> precedent of documenting added columns inline. Nullable because M2-era
> calls (still exercised by `tests/test_model_call_recording.py` et al.,
> which predate templates) pass none.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sul.enums import AgentRole
from sul.models._util import utcnow
from sul.models.base import Base

if TYPE_CHECKING:
    from sul.models.run import Run, Turn


class ModelCall(Base):
    """A single request/response exchange with an LLM provider (or FakeProvider)."""

    __tablename__ = "model_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("runs.id", ondelete="SET NULL"), index=True, default=None
    )
    agent: Mapped[AgentRole] = mapped_column(
        sa.Enum(
            AgentRole, native_enum=False, values_callable=lambda e: [m.value for m in e]
        )
    )
    provider: Mapped[str] = mapped_column(sa.String(64))
    model: Mapped[str] = mapped_column(sa.String(128))
    prompt_hash: Mapped[str] = mapped_column(sa.String(64))
    tokens_in: Mapped[int] = mapped_column(sa.Integer)
    tokens_out: Mapped[int] = mapped_column(sa.Integer)
    cost_usd: Mapped[float] = mapped_column(sa.Float)
    latency_ms: Mapped[int] = mapped_column(sa.Integer)
    seed: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    cached: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    template_version: Mapped[str | None] = mapped_column(sa.String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)

    run: Mapped[Run | None] = relationship(back_populates="model_calls")
    turns: Mapped[list[Turn]] = relationship(back_populates="model_call")

    def __repr__(self) -> str:
        return f"ModelCall(id={self.id!r}, provider={self.provider!r})"
