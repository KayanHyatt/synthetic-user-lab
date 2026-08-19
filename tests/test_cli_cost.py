"""`sul cost <study_id>` is M2's acceptance criterion (PROJECT_SPEC.md §M2:
"Cost for a demo run is queryable via `sul cost <study_id>`.").

Uses a real on-disk SQLite file (not the in-memory `session` fixture) because
the CLI opens its own engine from `Settings.database_url`, the way a real
invocation would -- an in-memory database wouldn't survive that.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sul import models
from sul.cli import app
from sul.config import get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.enums import AgentRole, ArtefactKind

runner = CliRunner()


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """A file-backed SQLite DB with one study whose spend includes both a
    Persona-run ModelCall and an Analyst ModelCall (run_id set, per the M1
    implementation note) -- the join in `sul cost` must not silently drop
    the Analyst's spend.
    """
    db_path = tmp_path / "sul.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        artefact = models.Artefact(
            name="a.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
        )
        session.add(artefact)
        session.flush()

        study = models.Study(
            name="cli cost study",
            research_goal="goal",
            artefact_id=artefact.id,
            config_hash="c1",
            git_sha="f" * 40,
        )
        session.add(study)
        session.flush()

        scenario = models.Scenario(study_id=study.id, task="task", questions=[])
        panel = models.Panel(study_id=study.id, seed=1, size=1, config_yaml="")
        session.add_all([scenario, panel])
        session.flush()

        persona = models.Persona(
            panel_id=panel.id, name="P1", segment="seg", attributes={}, card_text="card"
        )
        session.add(persona)
        session.flush()

        run = models.Run(
            study_id=study.id, persona_id=persona.id, scenario_id=scenario.id
        )
        session.add(run)
        session.flush()

        persona_call = models.ModelCall(
            run_id=run.id,
            agent=AgentRole.PERSONA,
            provider="fake",
            model="fake-1",
            prompt_hash="p1",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.25,
            latency_ms=10,
            seed=1,
        )
        analyst_call = models.ModelCall(
            run_id=run.id,
            agent=AgentRole.ANALYST,
            provider="anthropic",
            model="claude-opus-5",
            prompt_hash="p2",
            tokens_in=200,
            tokens_out=80,
            cost_usd=0.75,
            latency_ms=20,
            seed=None,
        )
        session.add_all([persona_call, analyst_call])
        session.commit()
        study_id = study.id

    engine.dispose()

    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    return study_id


def test_sul_cost_reports_total_including_analyst_spend(seeded_db: int) -> None:
    result = runner.invoke(app, ["cost", str(seeded_db)])

    assert result.exit_code == 0, result.output
    # 0.25 (persona) + 0.75 (analyst) = 1.00 -- the join must not drop the
    # Analyst's row (it has no Turn, only a ModelCall.run_id).
    assert "1.0000" in result.output
    assert "analyst" in result.output.lower()
    assert "persona" in result.output.lower()


def test_sul_cost_unknown_study_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "empty.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    engine.dispose()

    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["cost", "999999"])
    assert result.exit_code != 0
