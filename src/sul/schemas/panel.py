"""Panel/Persona boundary schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from sul import models
from sul.schemas.base import ORMModel


class PanelCreate(ORMModel):
    study_id: int
    seed: int
    size: int
    config_yaml: str

    def to_orm(self) -> models.Panel:
        return models.Panel(
            study_id=self.study_id,
            seed=self.seed,
            size=self.size,
            config_yaml=self.config_yaml,
        )


class PanelRead(ORMModel):
    id: int
    study_id: int
    seed: int
    size: int
    config_yaml: str


class PersonaCreate(ORMModel):
    """Input for a new Persona. Note what is absent: no research goal, no
    reference to other personas, no findings. See `sul.schemas.isolation`.
    """

    panel_id: int
    name: str
    segment: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    card_text: str

    def to_orm(self) -> models.Persona:
        return models.Persona(
            panel_id=self.panel_id,
            name=self.name,
            segment=self.segment,
            attributes=self.attributes,
            card_text=self.card_text,
        )


class PersonaRead(ORMModel):
    id: int
    panel_id: int
    name: str
    segment: str
    attributes: dict[str, Any]
    card_text: str
