"""`sul.runner.config`: loading `configs/study.example.yaml`-shaped documents
and materialising them into a full `Study` object graph.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import ArtefactKind
from sul.runner.config import load_study_config, materialize_study

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loads_the_shipped_example_config() -> None:
    config = load_study_config(REPO_ROOT / "configs" / "study.example.yaml")
    assert config.name
    assert config.artefact.kind == ArtefactKind.HTML
    assert config.scenario.task
    assert config.runner.concurrency == 1
    assert config.runner.max_followups == 3
    assert config.budget.max_cost_usd == 5.0


def test_materialize_study_persists_full_graph(
    session_factory: sessionmaker[Session],
) -> None:
    config = load_study_config(REPO_ROOT / "configs" / "study.example.yaml")
    with session_factory() as session:
        materialized = materialize_study(session, config, base_path=REPO_ROOT)
        session.commit()

        study = session.get(models.Study, materialized.study_id)
        assert study is not None
        assert study.research_goal == config.research_goal

        artefact = session.get(models.Artefact, materialized.artefact_id)
        assert artefact is not None
        assert "Nimbus Notes" in artefact.body

        scenario = session.get(models.Scenario, materialized.scenario_id)
        assert scenario is not None
        assert scenario.task == config.scenario.task

        panel = session.get(models.Panel, materialized.panel_id)
        assert panel is not None
        assert materialized.persona_count == panel.size == 40


def test_materialize_study_creates_a_persona_row_per_sampled_persona(
    session_factory: sessionmaker[Session],
) -> None:
    config = load_study_config(REPO_ROOT / "configs" / "study.example.yaml")
    with session_factory() as session:
        materialized = materialize_study(session, config, base_path=REPO_ROOT)
        session.commit()

        count = (
            session.query(models.Persona)
            .filter(models.Persona.panel_id == materialized.panel_id)
            .count()
        )
        assert count == materialized.persona_count
