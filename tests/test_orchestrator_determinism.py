"""Determinism the §M4 carry-forward requires of per-call seed derivation:
reproducible across separate process invocations, and independent of
concurrency/iteration order.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sul import models
from sul.db import create_all, make_engine, make_session_factory
from sul.providers.fake import FakeProvider
from sul.runner.orchestrator import run_study
from tests.support.study_factory import build_materialized_study


@pytest.fixture
def second_session_factory() -> Generator[sessionmaker[Session], None, None]:
    """A second, independent in-memory database -- `build_materialized_study`
    is not idempotent (its own docstring: two calls are two studies, not one
    resumed study), and calling it twice against the *same* database would
    collide on `Artefact.content_hash`'s uniqueness the second time.
    """
    engine = make_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_all(engine)
    factory = make_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


SCRIPT = Path(__file__).resolve().parent / "support" / "dump_transcripts_script.py"


def _run_dump_script(*, pythonhashseed: str) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = pythonhashseed
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_transcripts_identical_across_process_invocations_with_different_hashseed() -> (
    None
):
    """Two *separate* Python processes (the reproducibility bar the §M4
    carry-forward actually names) -- not two calls in one process, which
    would still pass under a `hash()`-keyed or dict/set-iteration-order bug
    because `PYTHONHASHSEED` is fixed for the life of one interpreter.
    """
    first = _run_dump_script(pythonhashseed="0")
    second = _run_dump_script(pythonhashseed="1")
    assert first == second
    assert len(json.loads(first)) == 20


async def _dump_transcripts(
    session_factory: sessionmaker[Session], *, concurrency: int
) -> dict[str, object]:
    materialized = build_materialized_study(session_factory)
    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        concurrency=concurrency,
    )
    with session_factory() as session:
        personas = (
            session.execute(
                select(models.Persona)
                .where(models.Persona.panel_id == materialized.panel_id)
                .order_by(models.Persona.id)
            )
            .scalars()
            .all()
        )
        dump: dict[str, object] = {}
        for persona in personas:
            run = session.execute(
                select(models.Run).where(
                    models.Run.study_id == materialized.study_id,
                    models.Run.persona_id == persona.id,
                )
            ).scalar_one()
            turns = (
                session.execute(
                    select(models.Turn)
                    .where(models.Turn.run_id == run.id)
                    .order_by(models.Turn.ordinal)
                )
                .scalars()
                .all()
            )
            dump[persona.name] = [(t.role.value, t.content) for t in turns]
        return dump


@pytest.mark.asyncio
async def test_concurrency_cap_does_not_change_per_persona_transcripts(
    session_factory: sessionmaker[Session],
    second_session_factory: sessionmaker[Session],
) -> None:
    """Two independent databases, run at concurrency 1 and 4 respectively.
    Seed derivation keys on persona *name* and turn index, not on any
    database id, so two separately-materialised (but identically-configured)
    studies must still produce identical per-persona transcripts.
    """
    sequential = await _dump_transcripts(session_factory, concurrency=1)
    concurrent = await _dump_transcripts(second_session_factory, concurrency=4)

    assert len(sequential) == 20
    assert sequential == concurrent
