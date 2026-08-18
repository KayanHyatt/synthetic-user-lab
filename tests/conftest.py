"""Shared fixtures: an in-memory SQLite session, and a sentinel-laden object graph."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import StaticPool
from sqlalchemy.orm import Session

from sul import models
from sul.db import create_all, make_engine, make_session_factory
from sul.enums import (
    AgentRole,
    ArtefactKind,
    FindingCategory,
    RunStatus,
    TurnRole,
)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """A session against a fresh in-memory SQLite database, one per test.

    `StaticPool` keeps the same in-memory connection alive for the whole
    test (SQLite's `:memory:` database is otherwise per-connection and
    vanishes as soon as the connection pool hands back a different one).
    """
    engine = make_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_all(engine)
    factory = make_session_factory(engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


class StudyGraph:
    """The full object graph for one study, with every persona-visible-adjacent
    string replaced by a distinctive sentinel so `test_isolation.py` can prove
    none of them leak into a `PersonaContext`.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

        self.artefact = models.Artefact(
            name="bad_onboarding.html",
            kind=ArtefactKind.HTML,
            content_hash="sentinel-content-hash-0001",
            body="<html>SENTINEL-ARTEFACT-BODY</html>",
        )
        session.add(self.artefact)
        session.flush()

        self.study = models.Study(
            name="Onboarding friction study",
            research_goal="SENTINEL-RESEARCH-GOAL-do-not-leak-to-personas",
            artefact_id=self.artefact.id,
            config_hash="sentinel-config-hash",
            git_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        )
        session.add(self.study)
        session.flush()

        self.panel = models.Panel(
            study_id=self.study.id,
            seed=42,
            size=2,
            config_yaml="seed: 42\nsize: 2\n",
        )
        session.add(self.panel)
        session.flush()

        self.persona_a = models.Persona(
            panel_id=self.panel.id,
            name="Persona A",
            segment="time_poor_professional",
            attributes={"tech_comfort": "high", "patience": "low"},
            card_text="You are SENTINEL-PERSONA-A-CARD, a time-poor professional.",
        )
        self.persona_b = models.Persona(
            panel_id=self.panel.id,
            name="Persona B",
            segment="cost_sensitive_student",
            attributes={"tech_comfort": "medium", "patience": "medium"},
            card_text="You are SENTINEL-PERSONA-B-CARD, a cost-sensitive student.",
        )
        session.add_all([self.persona_a, self.persona_b])
        session.flush()

        self.scenario = models.Scenario(
            study_id=self.study.id,
            task="SENTINEL-SCENARIO-TASK: sign up for the trial.",
            questions=["Was anything unclear?"],
        )
        session.add(self.scenario)
        session.flush()

        self.run = models.Run(
            study_id=self.study.id,
            persona_id=self.persona_a.id,
            scenario_id=self.scenario.id,
            status=RunStatus.COMPLETED,
        )
        session.add(self.run)
        session.flush()

        self.model_call = models.ModelCall(
            run_id=self.run.id,
            agent=AgentRole.PERSONA,
            provider="fake",
            model="fake-1",
            prompt_hash="sentinel-prompt-hash",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            latency_ms=10,
            seed=42,
            cached=True,
        )
        session.add(self.model_call)
        session.flush()

        self.turn_moderator = models.Turn(
            run_id=self.run.id,
            role=TurnRole.MODERATOR,
            ordinal=0,
            content="SENTINEL-MODERATOR-OPENING: try signing up.",
        )
        self.turn_persona = models.Turn(
            run_id=self.run.id,
            role=TurnRole.PERSONA,
            ordinal=1,
            content="I got confused by the pricing.",
            model_call_id=self.model_call.id,
        )
        session.add_all([self.turn_moderator, self.turn_persona])
        session.flush()

        self.finding = models.Finding(
            run_id=self.run.id,
            category=FindingCategory.CONFUSION,
            severity=3,
            summary="Persona was confused by the pricing table.",
            evidence_turn_id=self.turn_persona.id,
        )
        session.add(self.finding)
        session.flush()


@pytest.fixture
def study_graph(session: Session) -> StudyGraph:
    """A persisted, full object graph: Study -> Artefact/Panel/Scenario -> Persona
    -> Run -> Turn/ModelCall -> Finding, with sentinel strings throughout.
    """
    return StudyGraph(session)
