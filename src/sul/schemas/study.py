"""Study/Artefact/Scenario boundary schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from sul import models
from sul.enums import ArtefactKind
from sul.hashing import content_hash
from sul.schemas.base import ORMModel


class ArtefactCreate(ORMModel):
    """Input for a new Artefact. `content_hash` is always derived from `body`
    (never caller-supplied) so the uniqueness invariant can't be spoofed.
    """

    name: str
    kind: ArtefactKind
    body: str

    def to_orm(self) -> models.Artefact:
        return models.Artefact(
            name=self.name,
            kind=self.kind,
            body=self.body,
            content_hash=content_hash(self.body),
        )


class ArtefactRead(ORMModel):
    id: int
    name: str
    kind: ArtefactKind
    content_hash: str
    body: str


class StudyCreate(ORMModel):
    """Input for a new Study.

    `config_hash` is caller-supplied (typically `sul.hashing.config_hash`
    applied to a payload that includes `research_goal`) rather than derived
    here, since what belongs in "the config" is a runner-level decision, not
    a schema-level one.
    """

    name: str
    research_goal: str
    artefact_id: int
    config_hash: str
    git_sha: str

    def to_orm(self) -> models.Study:
        return models.Study(
            name=self.name,
            research_goal=self.research_goal,
            artefact_id=self.artefact_id,
            config_hash=self.config_hash,
            git_sha=self.git_sha,
        )


class StudyRead(ORMModel):
    id: int
    name: str
    research_goal: str
    artefact_id: int
    config_hash: str
    git_sha: str
    created_at: datetime


class ScenarioCreate(ORMModel):
    study_id: int
    task: str
    questions: list[Any] = Field(default_factory=list)

    def to_orm(self) -> models.Scenario:
        return models.Scenario(
            study_id=self.study_id, task=self.task, questions=self.questions
        )


class ScenarioRead(ORMModel):
    id: int
    study_id: int
    task: str
    questions: list[Any]
