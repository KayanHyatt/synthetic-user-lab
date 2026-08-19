"""Standalone script, run as a subprocess with a fresh in-memory database and
a caller-chosen `PYTHONHASHSEED`: the cross-process byte-stability check for
`sul.report` (PROJECT_SPEC.md §M5 plan, replacing an earlier same-process
"two renders of an identical ReportModel" test that could not catch a
wall-clock/hostname/iteration-order defect, since a value fixed once at
`ReportModel` construction is trivially identical across two renders in the
same process). Mirrors `tests/support/dump_transcripts_script.py`'s pattern.

Materialises the same fixed study, runs it via `FakeProvider`, builds a
report and renders both formats, and prints one canonical JSON line to
stdout. Two invocations of this script under different `PYTHONHASHSEED`
values must print byte-identical output.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy.pool import StaticPool  # noqa: E402

from sul.analysis.config import ClusteringConfig  # noqa: E402
from sul.db import make_engine, make_session_factory  # noqa: E402
from sul.models import Base  # noqa: E402
from sul.providers.fake import FakeProvider  # noqa: E402
from sul.report.build import build_report  # noqa: E402
from sul.report.html import render_html  # noqa: E402
from sul.report.markdown import render_markdown  # noqa: E402
from sul.runner.orchestrator import run_study  # noqa: E402
from tests.support.study_factory import build_materialized_study  # noqa: E402


async def _main() -> None:
    engine = make_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_20.yaml"
    )
    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
    )

    with session_factory() as session:
        report_model = build_report(
            session,
            study_id=materialized.study_id,
            clustering_config=ClusteringConfig(),
        )

    print(
        json.dumps(
            {
                "markdown": render_markdown(report_model),
                "html": render_html(report_model),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
