"""`sul.demo` (PROJECT_SPEC.md §M7): `sul demo` / `make demo` "runs a
complete study with `FakeProvider` and no API key" -- and, unlike the pre-M7
`make.ps1 demo` target (which printed a message and exited 0 regardless of
whether anything ran), actually verifies its own output.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from sul.demo import DemoResult, DemoVerificationError, run_demo, verify_demo
from sul.enums import RunStatus
from tests.support.report_factory import build_report_fixture
from tests.support.study_factory import build_materialized_study


async def test_run_demo_produces_a_usable_study(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{tmp_path / 'sul.db'}")
    from sul.config import get_settings

    get_settings.cache_clear()

    result = await run_demo()
    assert isinstance(result, DemoResult)
    assert result.completed_run_count > 0
    assert result.finding_count > 0
    assert result.cluster_count > 0


async def test_run_demo_never_dispatches_to_a_real_provider(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Belt and braces on top of `run_demo`'s own docstring guarantee: even
    if a future edit accidentally read `settings.provider`, the offline
    socket guard (`tests/conftest.py::_block_network`) would still catch a
    live dispatch. This just proves the demo completes with zero network
    activity regardless of what `SUL_PROVIDER`/`ANTHROPIC_API_KEY` happen to
    be set to in the environment.
    """
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{tmp_path / 'sul.db'}")
    monkeypatch.setenv("SUL_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    from sul.config import get_settings

    get_settings.cache_clear()

    result = await run_demo()  # would raise OfflineGuardError if it ever dispatched
    assert result.completed_run_count > 0


def test_verify_demo_raises_when_no_runs_completed(
    session_factory: sessionmaker,
) -> None:
    materialized = _empty_study(session_factory)
    with pytest.raises(DemoVerificationError, match="COMPLETED"):
        verify_demo(session_factory, study_id=materialized)


def test_verify_demo_raises_when_zero_findings(session_factory: sessionmaker) -> None:
    from sul import models

    with session_factory() as session:
        artefact = models.Artefact(
            name="a.html", kind="html", content_hash="h1", body="<html/>"
        )
        session.add(artefact)
        session.flush()
        study = models.Study(
            name="s",
            research_goal="g",
            artefact_id=artefact.id,
            config_hash="c",
            git_sha="f" * 40,
        )
        session.add(study)
        session.flush()
        scenario = models.Scenario(study_id=study.id, task="t", questions=[])
        panel = models.Panel(study_id=study.id, seed=1, size=1, config_yaml="")
        session.add_all([scenario, panel])
        session.flush()
        persona = models.Persona(
            panel_id=panel.id, name="P", segment="s", attributes={}, card_text="c"
        )
        session.add(persona)
        session.flush()
        run = models.Run(
            study_id=study.id,
            persona_id=persona.id,
            scenario_id=scenario.id,
            status=RunStatus.COMPLETED,
        )
        session.add(run)
        session.commit()
        study_id = study.id

    with pytest.raises(DemoVerificationError, match="findings"):
        verify_demo(session_factory, study_id=study_id)


def test_verify_demo_passes_against_a_populated_fixture(
    session_factory: sessionmaker,
) -> None:
    with session_factory() as session:
        fixture = build_report_fixture(session)

    result = verify_demo(session_factory, study_id=fixture.study_id)
    assert result.finding_count == 3
    assert result.cluster_count == 1
    # Ana, Ben, Cid completed; Dee failed; Eve pending -- three COMPLETED.
    assert result.completed_run_count == 3


def _empty_study(session_factory: sessionmaker) -> int:
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )
    return materialized.study_id
