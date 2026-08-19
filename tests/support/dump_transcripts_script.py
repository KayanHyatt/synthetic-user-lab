"""Standalone script, run as a subprocess with a fresh in-memory database and
a caller-chosen `PYTHONHASHSEED`, for the §M4 carry-forward's cross-process
seed-determinism check: "run it again, and independent of iteration order"
must hold *across separate process invocations*, not just two calls in one
process (a bug keyed on Python's salted `hash()` or on dict/set iteration
order would still pass an in-process test, since `PYTHONHASHSEED` is fixed
for the lifetime of one interpreter).

Materialises the same fixed study twice with fresh, empty databases and
prints a single canonical JSON line to stdout: every persona's name, its
full ordered transcript, and its findings. Two invocations of this script
under different `PYTHONHASHSEED` values must print byte-identical output.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sul import models  # noqa: E402
from sul.db import make_engine, make_session_factory  # noqa: E402
from sul.models import Base  # noqa: E402
from sul.providers.fake import FakeProvider  # noqa: E402
from sul.runner.orchestrator import run_study  # noqa: E402
from tests.support.study_factory import build_materialized_study  # noqa: E402


async def _main(concurrency: int) -> None:
    engine = make_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

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
            findings = (
                session.execute(
                    select(models.Finding).where(models.Finding.run_id == run.id)
                )
                .scalars()
                .all()
            )
            dump[persona.name] = {
                "transcript": [[t.role.value, t.content] for t in turns],
                "findings": sorted(
                    [f.category.value, f.severity, f.summary] for f in findings
                ),
            }

    print(json.dumps(dump, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    concurrency_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    asyncio.run(_main(concurrency_arg))
