"""Create -> ORM -> persist -> Read round-trips for every entity's boundary schema."""

from __future__ import annotations

from sqlalchemy.orm import Session

from sul.enums import AgentRole, ArtefactKind, FindingCategory, RunStatus, TurnRole
from sul.hashing import config_hash, content_hash
from sul.schemas import (
    ArtefactCreate,
    ArtefactRead,
    FindingCreate,
    FindingRead,
    ModelCallCreate,
    ModelCallRead,
    PanelCreate,
    PanelRead,
    PersonaCreate,
    PersonaRead,
    RunCreate,
    RunRead,
    ScenarioCreate,
    ScenarioRead,
    StudyCreate,
    StudyRead,
    TurnCreate,
    TurnRead,
)


def test_artefact_round_trip(session: Session) -> None:
    create = ArtefactCreate(
        name="good_onboarding.html", kind=ArtefactKind.HTML, body="<p>hi</p>"
    )
    orm = create.to_orm()
    assert orm.content_hash == content_hash("<p>hi</p>")

    session.add(orm)
    session.flush()

    read = ArtefactRead.model_validate(orm)
    assert read.id == orm.id
    assert read.kind == ArtefactKind.HTML
    assert read.content_hash == content_hash("<p>hi</p>")
    assert read.body == "<p>hi</p>"


def test_study_round_trip(session: Session) -> None:
    artefact = ArtefactCreate(
        name="a.html", kind=ArtefactKind.HTML, body="<p>a</p>"
    ).to_orm()
    session.add(artefact)
    session.flush()

    goal = "Find pricing confusion"
    create = StudyCreate(
        name="Study 1",
        research_goal=goal,
        artefact_id=artefact.id,
        config_hash=config_hash({"research_goal": goal}),
        git_sha="a" * 40,
    )
    orm = create.to_orm()
    session.add(orm)
    session.flush()

    read = StudyRead.model_validate(orm)
    assert read.id == orm.id
    assert read.research_goal == goal
    assert read.artefact_id == artefact.id
    assert read.created_at is not None


def test_scenario_round_trip(session: Session) -> None:
    artefact = ArtefactCreate(
        name="a.html", kind=ArtefactKind.HTML, body="<p>a</p>"
    ).to_orm()
    session.add(artefact)
    session.flush()
    study = StudyCreate(
        name="s",
        research_goal="g",
        artefact_id=artefact.id,
        config_hash="h",
        git_sha="a" * 40,
    ).to_orm()
    session.add(study)
    session.flush()

    create = ScenarioCreate(
        study_id=study.id, task="Sign up", questions=["Was it clear?"]
    )
    orm = create.to_orm()
    session.add(orm)
    session.flush()

    read = ScenarioRead.model_validate(orm)
    assert read.task == "Sign up"
    assert read.questions == ["Was it clear?"]


def test_panel_and_persona_round_trip(session: Session) -> None:
    artefact = ArtefactCreate(
        name="a.html", kind=ArtefactKind.HTML, body="<p>a</p>"
    ).to_orm()
    session.add(artefact)
    session.flush()
    study = StudyCreate(
        name="s",
        research_goal="g",
        artefact_id=artefact.id,
        config_hash="h",
        git_sha="a" * 40,
    ).to_orm()
    session.add(study)
    session.flush()

    panel = PanelCreate(
        study_id=study.id, seed=1, size=1, config_yaml="seed: 1\n"
    ).to_orm()
    session.add(panel)
    session.flush()
    panel_read = PanelRead.model_validate(panel)
    assert panel_read.seed == 1

    persona = PersonaCreate(
        panel_id=panel.id,
        name="P1",
        segment="student",
        attributes={"tech_comfort": "high"},
        card_text="You are a student.",
    ).to_orm()
    session.add(persona)
    session.flush()

    persona_read = PersonaRead.model_validate(persona)
    assert persona_read.attributes == {"tech_comfort": "high"}
    assert persona_read.card_text == "You are a student."


def test_run_and_turn_round_trip(session: Session) -> None:
    artefact = ArtefactCreate(
        name="a.html", kind=ArtefactKind.HTML, body="<p>a</p>"
    ).to_orm()
    session.add(artefact)
    session.flush()
    study = StudyCreate(
        name="s",
        research_goal="g",
        artefact_id=artefact.id,
        config_hash="h",
        git_sha="a" * 40,
    ).to_orm()
    session.add(study)
    session.flush()
    panel = PanelCreate(study_id=study.id, seed=1, size=1, config_yaml="").to_orm()
    session.add(panel)
    session.flush()
    persona = PersonaCreate(
        panel_id=panel.id, name="P1", segment="s", attributes={}, card_text="card"
    ).to_orm()
    scenario = ScenarioCreate(study_id=study.id, task="t", questions=[]).to_orm()
    session.add_all([persona, scenario])
    session.flush()

    run = RunCreate(
        study_id=study.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status=RunStatus.RUNNING,
    ).to_orm()
    session.add(run)
    session.flush()
    run_read = RunRead.model_validate(run)
    assert run_read.status == RunStatus.RUNNING
    assert run_read.started_at is None

    turn = TurnCreate(
        run_id=run.id, role=TurnRole.MODERATOR, ordinal=0, content="hi"
    ).to_orm()
    session.add(turn)
    session.flush()
    turn_read = TurnRead.model_validate(turn)
    assert turn_read.role == TurnRole.MODERATOR
    assert turn_read.model_call_id is None


def test_model_call_round_trip(session: Session) -> None:
    create = ModelCallCreate(
        run_id=None,
        agent=AgentRole.ANALYST,
        provider="fake",
        model="fake-1",
        prompt_hash="ph",
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.002,
        latency_ms=50,
        seed=7,
        cached=False,
    )
    orm = create.to_orm()
    session.add(orm)
    session.flush()

    read = ModelCallRead.model_validate(orm)
    assert read.agent == AgentRole.ANALYST
    assert read.cost_usd == 0.002
    assert read.created_at is not None


def test_finding_round_trip(session: Session) -> None:
    artefact = ArtefactCreate(
        name="a.html", kind=ArtefactKind.HTML, body="<p>a</p>"
    ).to_orm()
    session.add(artefact)
    session.flush()
    study = StudyCreate(
        name="s",
        research_goal="g",
        artefact_id=artefact.id,
        config_hash="h",
        git_sha="a" * 40,
    ).to_orm()
    session.add(study)
    session.flush()
    panel = PanelCreate(study_id=study.id, seed=1, size=1, config_yaml="").to_orm()
    session.add(panel)
    session.flush()
    persona = PersonaCreate(
        panel_id=panel.id, name="P1", segment="s", attributes={}, card_text="card"
    ).to_orm()
    scenario = ScenarioCreate(study_id=study.id, task="t", questions=[]).to_orm()
    session.add_all([persona, scenario])
    session.flush()
    run = RunCreate(
        study_id=study.id, persona_id=persona.id, scenario_id=scenario.id
    ).to_orm()
    session.add(run)
    session.flush()
    turn = TurnCreate(
        run_id=run.id, role=TurnRole.PERSONA, ordinal=0, content="confused"
    ).to_orm()
    session.add(turn)
    session.flush()

    create = FindingCreate(
        run_id=run.id,
        category=FindingCategory.CONFUSION,
        severity=4,
        summary="Confused by pricing",
        evidence_turn_id=turn.id,
    )
    orm = create.to_orm()
    session.add(orm)
    session.flush()

    read = FindingRead.model_validate(orm)
    assert read.category == FindingCategory.CONFUSION
    assert read.severity == 4
    assert read.evidence_turn_id == turn.id
    assert read.cluster_id is None
