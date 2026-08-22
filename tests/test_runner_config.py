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


def test_materialize_study_reuses_an_existing_artefact_with_the_same_content(
    session_factory: sessionmaker[Session],
) -> None:
    """PROJECT_SPEC.md §M7 deviation: `Artefact.content_hash` is a UNIQUE
    content-address, but materialisation never looked one up before
    inserting -- two studies against the same artefact body (e.g.
    `configs/study.example.yaml` and `configs/study.demo.yaml`, which both
    point at `artefacts/bad_onboarding.html`) used to raise `IntegrityError`
    on the second call instead of reusing the first call's `Artefact` row.
    Found by running `sul demo` twice against a real, persisted database.
    """
    config_a = load_study_config(REPO_ROOT / "configs" / "study.example.yaml")
    config_b = load_study_config(REPO_ROOT / "configs" / "study.demo.yaml")
    assert config_a.artefact.path == config_b.artefact.path  # same body, precondition

    with session_factory() as session:
        first = materialize_study(session, config_a, base_path=REPO_ROOT)
        session.commit()
        second = materialize_study(session, config_b, base_path=REPO_ROOT)
        session.commit()

        assert first.artefact_id == second.artefact_id  # deduplicated, not collided
        assert first.study_id != second.study_id  # still two independent studies

        artefact_count = session.query(models.Artefact).count()
        assert artefact_count == 1


def test_materialize_study_still_creates_distinct_artefacts_for_distinct_content(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """The dedup above must be keyed on content, not on config path or name --
    two genuinely different artefact bodies still get two distinct rows."""
    import yaml

    config_path = REPO_ROOT / "configs" / "study.example.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    (tmp_path / "artefact_a.html").write_text("<html>A</html>", encoding="utf-8")
    (tmp_path / "artefact_b.html").write_text("<html>B</html>", encoding="utf-8")
    raw["panel_config_path"] = str(REPO_ROOT / raw["panel_config_path"])

    from sul.runner.config import StudyRunConfig

    config_a = StudyRunConfig.model_validate(
        {**raw, "artefact": {**raw["artefact"], "path": "artefact_a.html"}}
    )
    config_b = StudyRunConfig.model_validate(
        {**raw, "artefact": {**raw["artefact"], "path": "artefact_b.html"}}
    )

    with session_factory() as session:
        first = materialize_study(session, config_a, base_path=tmp_path)
        session.commit()
        second = materialize_study(session, config_b, base_path=tmp_path)
        session.commit()

        assert first.artefact_id != second.artefact_id
        assert session.query(models.Artefact).count() == 2
