"""PROJECT_SPEC.md §M4's literal acceptance criterion:

    20 personas x 1 scenario against artefacts/bad_onboarding.html completes
    offline via FakeProvider; all transcripts and findings persist; kill the
    process at 50% and re-run -- it completes without duplicate Run rows.

Two tests: the first exercises the "completes offline, everything persists"
half in-process against the real `FakeProvider` and the real fixture
artefact; the second exercises "kill at 50% and resume" as a genuine
separate OS process (see `tests/support/run_study_script.py`'s docstring for
why an in-process simulated exception is not a faithful enough stand-in).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.db import make_engine, make_session_factory
from sul.enums import RunStatus
from sul.providers.fake import FakeProvider
from sul.runner.orchestrator import run_study
from tests.support.study_factory import DEFAULT_ARTEFACT_PATH, build_materialized_study

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_20_personas_1_scenario_completes_offline_and_persists_everything(
    session_factory: sessionmaker[Session],
) -> None:
    materialized = build_materialized_study(session_factory)
    assert materialized.persona_count == 20

    with session_factory() as session:
        artefact = session.get(models.Artefact, materialized.artefact_id)
        assert artefact is not None
        assert artefact.body == (REPO_ROOT / DEFAULT_ARTEFACT_PATH).read_text(
            encoding="utf-8"
        )

    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
    )

    assert summary.total_personas == 20
    assert len(summary.completed) == 20
    assert summary.failed == []

    with session_factory() as session:
        runs = (
            session.execute(
                select(models.Run).where(models.Run.study_id == materialized.study_id)
            )
            .scalars()
            .all()
        )
        assert len(runs) == 20
        assert all(r.status == RunStatus.COMPLETED for r in runs)

        for run in runs:
            turn_count = session.execute(
                select(func.count(models.Turn.id)).where(models.Turn.run_id == run.id)
            ).scalar_one()
            # Opening (moderator) + at least one persona reply, at minimum.
            assert turn_count >= 2, f"run {run.id} has no persisted transcript"

        total_findings = session.execute(
            select(func.count(models.Finding.id))
            .select_from(models.Finding)
            .join(models.Run, models.Run.id == models.Finding.run_id)
            .where(models.Run.study_id == materialized.study_id)
        ).scalar_one()
        assert total_findings > 0, "no findings persisted for any run"

        # Every finding's evidence_turn_id resolves to a real Turn in the
        # *same* run -- not just any Turn row in the database.
        findings = (
            session.execute(
                select(models.Finding)
                .join(models.Run, models.Run.id == models.Finding.run_id)
                .where(models.Run.study_id == materialized.study_id)
            )
            .scalars()
            .all()
        )
        for finding in findings:
            evidence_turn = session.get(models.Turn, finding.evidence_turn_id)
            assert evidence_turn is not None
            assert evidence_turn.run_id == finding.run_id


def test_kill_at_50_percent_and_resume_completes_without_duplicate_runs(
    tmp_path: Path,
) -> None:
    """The literal acceptance clause, run as a genuine separate OS process
    (see `tests/support/run_study_script.py` for why an in-process simulated
    exception isn't a faithful enough stand-in for "kill the process": a
    straggling `asyncio.to_thread` write from a merely-cancelled coroutine
    can land after a later in-process resume has already started, which a
    real killed process's write never can, since the process it would come
    from no longer exists).
    """
    db_path = tmp_path / "m4_acceptance.db"
    state_path = tmp_path / "study_ids.json"
    script = Path(__file__).resolve().parent / "support" / "run_study_script.py"

    first = subprocess.run(
        [
            sys.executable,
            str(script),
            str(db_path),
            str(state_path),
            "--crash-after",
            "50",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "SIMULATED KILL" in first.stderr, first.stderr
    assert "DONE" not in first.stdout

    engine = make_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        runs_after_crash = session.execute(select(models.Run)).scalars().all()
        assert len(runs_after_crash) == 20, "resumability needs every Run row upfront"
        completed_after_crash = sum(
            1 for r in runs_after_crash if r.status == RunStatus.COMPLETED
        )
        assert 0 < completed_after_crash < 20, (
            f"expected a partial panel, got {completed_after_crash}/20 completed"
        )
    engine.dispose()

    second = subprocess.run(
        [sys.executable, str(script), str(db_path), str(state_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert second.returncode == 0, second.stderr
    assert "DONE" in second.stdout

    engine = make_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        runs_after_resume = session.execute(select(models.Run)).scalars().all()
        # The decisive assertion: still exactly 20 Run rows -- resuming never
        # duplicates a Run for a persona that already had one.
        assert len(runs_after_resume) == 20
        assert all(r.status == RunStatus.COMPLETED for r in runs_after_resume)

        for run in runs_after_resume:
            ordinals = (
                session.execute(
                    select(models.Turn.ordinal)
                    .where(models.Turn.run_id == run.id)
                    .order_by(models.Turn.ordinal)
                )
                .scalars()
                .all()
            )
            assert len(ordinals) >= 2
            # No duplicate/gapped ordinals -- a resumed run that appended
            # instead of clearing its partial transcript would either trip
            # Turn's own (run_id, ordinal) uniqueness at write time or leave
            # a gap; assert the observable shape too.
            assert ordinals == list(range(len(ordinals)))
    engine.dispose()
