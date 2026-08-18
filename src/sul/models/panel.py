"""Panel and Persona: the population sampled for a study.

Isolation boundary: `Persona.panel` and `Panel.study` are mapped
`lazy="raise"`. A persona agent must only ever be built from
`sul.schemas.isolation.PersonaContext`, never from a live ORM `Persona`
instance — but code paths change, and someone will eventually hand a
`Persona` object to the wrong function. `lazy="raise"` turns what would
otherwise be a silent lazy-load of `Persona.panel.study.research_goal` into
an immediate `InvalidRequestError`. Any legitimate traversal from a Persona up
to its Study (e.g. in the runner or the report renderer, which are not
persona-bound code) must use an explicit `selectinload`/`joinedload` — which
is the point: it makes every such crossing deliberate and greppable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sul.models.base import Base

if TYPE_CHECKING:
    from sul.models.run import Run
    from sul.models.study import Study


class Panel(Base):
    """A sampled population of personas for one study, seeded for reproducibility."""

    __tablename__ = "panels"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(
        sa.ForeignKey("studies.id", ondelete="CASCADE"), index=True
    )
    seed: Mapped[int] = mapped_column(sa.Integer)
    size: Mapped[int] = mapped_column(sa.Integer)
    config_yaml: Mapped[str] = mapped_column(sa.Text)

    study: Mapped[Study] = relationship(back_populates="panels", lazy="raise")
    personas: Mapped[list[Persona]] = relationship(
        back_populates="panel", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"Panel(id={self.id!r}, study_id={self.study_id!r}, size={self.size!r})"


class Persona(Base):
    """A single simulated user. Must never carry the research goal, other personas,
    or prior findings — only its own card and segment attributes.
    """

    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        sa.ForeignKey("panels.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(sa.String(255))
    segment: Mapped[str] = mapped_column(sa.String(255))
    attributes: Mapped[dict[str, Any]] = mapped_column(sa.JSON, default=dict)
    card_text: Mapped[str] = mapped_column(sa.Text)

    panel: Mapped[Panel] = relationship(back_populates="personas", lazy="raise")
    runs: Mapped[list[Run]] = relationship(
        back_populates="persona", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"Persona(id={self.id!r}, name={self.name!r}, segment={self.segment!r})"
