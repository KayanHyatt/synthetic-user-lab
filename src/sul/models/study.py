"""Study, Artefact and Scenario: the top-level configuration of a research run.

`Study.research_goal` is deliberately the only place the research question is
recorded — it is the string the persona-isolation boundary (see
`sul.schemas.isolation.PersonaContext`) must never leak. Persona rows never
carry a foreign key back to it directly; the only path is
`Persona -> Panel -> Study`, and that path is fenced off with `lazy="raise"`
in `sul.models.panel`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sul.enums import ArtefactKind
from sul.models._util import utcnow
from sul.models.base import Base

if TYPE_CHECKING:
    from sul.models.panel import Panel
    from sul.models.run import Run


class Artefact(Base):
    """A product artefact (landing page, onboarding flow, docs) shown to personas."""

    __tablename__ = "artefacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    kind: Mapped[ArtefactKind] = mapped_column(
        sa.Enum(
            ArtefactKind,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        )
    )
    content_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    body: Mapped[str] = mapped_column(sa.Text)

    studies: Mapped[list[Study]] = relationship(back_populates="artefact")

    def __repr__(self) -> str:
        return f"Artefact(id={self.id!r}, name={self.name!r}, kind={self.kind!r})"


class Study(Base):
    """A research study: one research goal, one artefact, its panels/scenarios."""

    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    research_goal: Mapped[str] = mapped_column(sa.Text)
    artefact_id: Mapped[int] = mapped_column(sa.ForeignKey("artefacts.id"))
    config_hash: Mapped[str] = mapped_column(sa.String(64))
    git_sha: Mapped[str] = mapped_column(sa.String(40))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=utcnow)

    artefact: Mapped[Artefact] = relationship(back_populates="studies")
    panels: Mapped[list[Panel]] = relationship(
        back_populates="study", cascade="all, delete-orphan", passive_deletes=True
    )
    scenarios: Mapped[list[Scenario]] = relationship(
        back_populates="study", cascade="all, delete-orphan", passive_deletes=True
    )
    runs: Mapped[list[Run]] = relationship(
        back_populates="study", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"Study(id={self.id!r}, name={self.name!r})"


class Scenario(Base):
    """A task given to each persona in a study, plus moderator follow-up questions."""

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(
        sa.ForeignKey("studies.id", ondelete="CASCADE"), index=True
    )
    task: Mapped[str] = mapped_column(sa.Text)
    questions: Mapped[list[Any]] = mapped_column(sa.JSON, default=list)

    study: Mapped[Study] = relationship(back_populates="scenarios")
    runs: Mapped[list[Run]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"Scenario(id={self.id!r}, study_id={self.study_id!r})"
