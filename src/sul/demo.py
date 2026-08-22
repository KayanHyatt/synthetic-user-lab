"""`sul demo` / `make demo` (PROJECT_SPEC.md §M7): "`make demo` runs a
complete study with `FakeProvider` and no API key."

The pre-M7 `make.ps1 demo` target printed a warning and exited 0 regardless
of whether anything actually ran (`make.ps1`'s own `Demo` function, before
this milestone: `Write-Host "demo: not implemented yet..."`, no assertion
anywhere). ``.\\make.ps1 demo`` now runs `uv run sul demo`, and `sul demo`
re-opens the database it just wrote and asserts it produced a usable study --
`$LASTEXITCODE` carries a real verification, not a printed message. That
assertion is `verify_demo`, below: a plain Python function, independently
callable (and independently tested) without going through the CLI or a
subprocess at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul.config import Settings, get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.enums import RunStatus
from sul.models import Run, Scenario, Study
from sul.providers.fake import FakeProvider
from sul.report.build import build_report
from sul.runner.config import load_study_config, materialize_study
from sul.runner.orchestrator import run_study

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDY_CONFIG_PATH = REPO_ROOT / "configs" / "study.demo.yaml"


class DemoVerificationError(RuntimeError):
    """`sul demo` ran, but its own output failed the completeness check --
    never silently reported as success.
    """


@dataclass(frozen=True)
class DemoResult:
    study_id: int
    completed_run_count: int
    finding_count: int
    cluster_count: int


def verify_demo(session_factory: sessionmaker[Session], *, study_id: int) -> DemoResult:
    """Re-open the database and assert `study_id` is actually demo-worthy:
    at least one `COMPLETED` run, at least one `Finding`, at least one
    cluster once `build_report` runs over it, and every rendered cluster
    carries real evidence. Raises `DemoVerificationError` (never returns a
    "partial success") the moment any of those isn't true.

    Independently callable -- and independently tested
    (`tests/test_demo.py`) -- against any already-populated study, not just
    one `run_demo` itself produced; that is what makes this a real assertion
    about the database rather than a self-fulfilling check on `run_demo`'s
    own in-memory state.
    """
    with session_factory() as session:
        completed = (
            session.execute(
                select(Run.id).where(
                    Run.study_id == study_id, Run.status == RunStatus.COMPLETED
                )
            )
            .scalars()
            .all()
        )
        if not completed:
            raise DemoVerificationError(
                f"study {study_id}: zero COMPLETED runs -- sul demo did not "
                "produce a usable study"
            )

        report = build_report(session, study_id=study_id)

    if report.total_findings == 0:
        raise DemoVerificationError(
            f"study {study_id}: zero findings -- the report would render empty"
        )
    if not report.clusters:
        raise DemoVerificationError(
            f"study {study_id}: {report.total_findings} finding(s) but zero "
            "clusters -- build_report produced no clusters"
        )
    for cluster in report.clusters:
        if not cluster.evidence:
            raise DemoVerificationError(
                f"study {study_id}: cluster {cluster.cluster_id} has no evidence"
            )
        for item in cluster.evidence:
            if not item.quote:
                raise DemoVerificationError(
                    f"study {study_id}: finding {item.finding_id}'s evidence "
                    "quote is empty"
                )

    return DemoResult(
        study_id=study_id,
        completed_run_count=len(completed),
        finding_count=report.total_findings,
        cluster_count=len(report.clusters),
    )


async def run_demo(
    *,
    settings: Settings | None = None,
    study_config_path: Path | None = None,
) -> DemoResult:
    """Materialise and run `configs/study.demo.yaml` end to end against an
    explicitly constructed `FakeProvider()` -- never `settings.provider`,
    never `sul.cli._select_validate_provider` (§M6's cassette auto-detection
    is `sul validate`'s own concern; PROJECT_SPEC.md §M7 5.4 requires the
    demo be unable to replay a cassette by accident or dispatch a live call,
    and constructing `FakeProvider` directly, with no code path to any other
    provider, is what makes that true structurally rather than by
    convention).

    **Safe to run more than once against the same database.**
    `sul.runner.config.materialize_study` inserts a fresh `Artefact` row on
    every call and never checks for an existing one -- fine for `sul run`
    (each invocation is a deliberately new study), but `configs/study.demo
    .yaml` and `configs/study.example.yaml` both point at the same
    `artefacts/bad_onboarding.html`, and `Artefact.content_hash` is UNIQUE:
    a second `sul demo` (or a `sul demo` after any earlier `sul run` against
    that same artefact) would otherwise crash with an `IntegrityError`
    rather than the "look, it worked" a reviewer running the command twice
    should see. Found by running `.\\make.ps1 demo` for real against this
    repo's own dev `sul.db`, which already had a `bad_onboarding.html`
    artefact in it from earlier sessions -- the pytest suite alone, always
    starting from an empty database, never exercised this path. Fixed here,
    scoped to the demo only (by reusing an existing `Study` row with the
    same `name` rather than re-materialising): `materialize_study`'s general
    non-idempotency for `sul run` is a real, separate gap, left open --
    PROJECT_SPEC.md's §M7 deviation note says so explicitly.
    """
    resolved_settings = settings or get_settings()
    config_path = study_config_path or DEFAULT_STUDY_CONFIG_PATH

    engine = make_engine(resolved_settings.database_url)
    create_all(engine)
    session_factory = make_session_factory(engine)

    config = load_study_config(config_path)
    with session_factory() as session:
        existing_study_id = session.execute(
            select(Study.id).where(Study.name == config.name)
        ).scalar_one_or_none()
        if existing_study_id is not None:
            study_id = existing_study_id
            scenario_id = session.execute(
                select(Scenario.id).where(Scenario.study_id == study_id)
            ).scalar_one()
        else:
            materialized = materialize_study(session, config, base_path=REPO_ROOT)
            session.commit()
            study_id = materialized.study_id
            scenario_id = materialized.scenario_id

    await run_study(
        session_factory,
        study_id=study_id,
        scenario_id=scenario_id,
        provider=FakeProvider(),
        provider_name="fake",
        model=config.runner.model,
        temperature=config.runner.temperature,
        max_tokens=config.runner.max_tokens,
        max_followups=config.runner.max_followups,
        concurrency=config.runner.concurrency,
    )

    result = verify_demo(session_factory, study_id=study_id)
    engine.dispose()
    return result


__all__ = [
    "DEFAULT_STUDY_CONFIG_PATH",
    "DemoResult",
    "DemoVerificationError",
    "run_demo",
    "verify_demo",
]
