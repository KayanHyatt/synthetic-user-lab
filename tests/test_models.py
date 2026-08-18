"""Spec acceptance: create a full object graph and query it. Plus constraints,
cascade behaviour, and FK enforcement.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sul import models
from sul.enums import AgentRole, ArtefactKind, FindingCategory, RunStatus, TurnRole
from tests.conftest import StudyGraph


def test_full_graph_round_trips(session: Session, study_graph: StudyGraph) -> None:
    """Spec acceptance criterion: create a full object graph and query it back."""
    session.expire_all()

    study = session.get(models.Study, study_graph.study.id)
    assert study is not None
    assert study.name == "Onboarding friction study"
    assert study.artefact_id == study_graph.artefact.id

    run = session.get(models.Run, study_graph.run.id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED

    turns = (
        session.execute(
            sa.select(models.Turn)
            .where(models.Turn.run_id == run.id)
            .order_by(models.Turn.ordinal)
        )
        .scalars()
        .all()
    )
    assert [t.role for t in turns] == [TurnRole.MODERATOR, TurnRole.PERSONA]

    finding = session.get(models.Finding, study_graph.finding.id)
    assert finding is not None
    assert finding.evidence_turn_id == study_graph.turn_persona.id
    assert finding.category == FindingCategory.CONFUSION

    model_call = session.get(models.ModelCall, study_graph.model_call.id)
    assert model_call is not None
    assert model_call.agent == AgentRole.PERSONA
    assert model_call.run_id == run.id


def test_foreign_keys_are_enforced(session: Session) -> None:
    """Without PRAGMA foreign_keys=ON, this insert would silently succeed."""
    bogus = models.Scenario(study_id=999_999, task="orphan", questions=[])
    session.add(bogus)
    with pytest.raises(IntegrityError):
        session.flush()


def test_run_triple_is_unique(session: Session, study_graph: StudyGraph) -> None:
    """The (study_id, persona_id, scenario_id) uniqueness is what makes the
    M4 orchestrator's resume-without-duplicates behaviour possible.
    """
    duplicate = models.Run(
        study_id=study_graph.study.id,
        persona_id=study_graph.persona_a.id,
        scenario_id=study_graph.scenario.id,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_turn_ordinal_is_unique_per_run(
    session: Session, study_graph: StudyGraph
) -> None:
    duplicate = models.Turn(
        run_id=study_graph.run.id,
        role=TurnRole.PERSONA,
        ordinal=1,
        content="duplicate ordinal",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


def test_artefact_content_hash_is_unique(
    session: Session, study_graph: StudyGraph
) -> None:
    duplicate = models.Artefact(
        name="another.html",
        kind=ArtefactKind.HTML,
        content_hash=study_graph.artefact.content_hash,
        body="different body, same hash",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("severity", [0, 6, -1])
def test_finding_severity_check_constraint(
    session: Session, study_graph: StudyGraph, severity: int
) -> None:
    bad = models.Finding(
        run_id=study_graph.run.id,
        category=FindingCategory.BLOCKER,
        severity=severity,
        summary="out of range severity",
        evidence_turn_id=study_graph.turn_persona.id,
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_run_cascades_to_turns_and_findings(
    session: Session, study_graph: StudyGraph
) -> None:
    """Cascaded deletes happen at the DB level (passive_deletes=True), not through
    the ORM's own unit-of-work, so children are checked with a fresh SELECT
    rather than `session.get` — the latter can return a stale identity-map
    object for a row the DB cascade removed without the ORM's knowledge.
    """
    run_id = study_graph.run.id
    turn_ids = [study_graph.turn_moderator.id, study_graph.turn_persona.id]
    finding_id = study_graph.finding.id

    session.delete(study_graph.run)
    session.flush()
    session.expire_all()

    assert session.get(models.Run, run_id) is None
    remaining_turns = (
        session.execute(sa.select(models.Turn.id).where(models.Turn.id.in_(turn_ids)))
        .scalars()
        .all()
    )
    assert remaining_turns == []
    remaining_finding = session.execute(
        sa.select(models.Finding.id).where(models.Finding.id == finding_id)
    ).scalar_one_or_none()
    assert remaining_finding is None


def test_deleting_study_cascades_through_panel_to_personas(
    session: Session, study_graph: StudyGraph
) -> None:
    study_id = study_graph.study.id
    panel_id = study_graph.panel.id
    persona_ids = [study_graph.persona_a.id, study_graph.persona_b.id]
    run_id = study_graph.run.id

    session.delete(study_graph.study)
    session.flush()
    session.expire_all()

    assert session.get(models.Study, study_id) is None
    remaining_panels = session.execute(
        sa.select(models.Panel.id).where(models.Panel.id == panel_id)
    ).scalar_one_or_none()
    assert remaining_panels is None
    remaining_personas = (
        session.execute(
            sa.select(models.Persona.id).where(models.Persona.id.in_(persona_ids))
        )
        .scalars()
        .all()
    )
    assert remaining_personas == []
    remaining_run = session.execute(
        sa.select(models.Run.id).where(models.Run.id == run_id)
    ).scalar_one_or_none()
    assert remaining_run is None


def test_deleting_model_call_sets_turn_fk_null_not_cascade(
    session: Session, study_graph: StudyGraph
) -> None:
    """Deleting a ModelCall must not delete transcript."""
    turn_id = study_graph.turn_persona.id

    session.delete(study_graph.model_call)
    session.flush()
    session.expire_all()

    turn = session.get(models.Turn, turn_id)
    assert turn is not None
    assert turn.model_call_id is None


def test_model_call_run_id_is_nullable(session: Session) -> None:
    """Analyst calls can be recorded with no associated Run row's Turn (M2's
    `sul cost <study_id>` needs Analyst spend attributed even absent a Turn).
    """
    call = models.ModelCall(
        run_id=None,
        agent=AgentRole.ANALYST,
        provider="fake",
        model="fake-1",
        prompt_hash="hash",
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.0,
        latency_ms=1,
    )
    session.add(call)
    session.flush()
    assert call.id is not None
