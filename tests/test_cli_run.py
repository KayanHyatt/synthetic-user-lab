"""`sul run <study.yaml>` (PROJECT_SPEC.md §M7): materialise and run a study
end to end. Uses a real on-disk SQLite file (not the in-memory `session`
fixture) since the CLI opens its own engine from `Settings.database_url`,
mirroring `tests/test_cli_report.py`'s own pattern.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sul.cli import app
from sul.config import get_settings

runner = CliRunner()


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "sul.db"
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    return db_path


def test_run_completes_a_study_against_fakeprovider(fresh_db: Path) -> None:
    result = runner.invoke(app, ["run", "configs/study.demo.yaml"])
    assert result.exit_code == 0, result.output
    assert "study_id=" in result.output
    assert "completed_this_run=6" in result.output
    assert "failed=0" in result.output


def test_run_defaults_to_fake_and_never_needs_a_key(fresh_db: Path) -> None:
    """No `--provider` flag at all -- the default is `fake`, which needs no
    key regardless of what `.env`/the environment happen to carry.
    """
    result = runner.invoke(app, ["run", "configs/study.demo.yaml"])
    assert result.exit_code == 0, result.output


def test_run_with_unconfigured_anthropic_provider_fails_clearly(
    fresh_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty string, not `delenv`: this repo's own `.env` may carry a real
    # `ANTHROPIC_API_KEY` for local dev, and pydantic-settings' default
    # source order only lets a *present* environment variable override the
    # `.env` file's value -- deleting it from `os.environ` would just let
    # the `.env` value show back through, defeating the "not configured"
    # case this test means to exercise (see `tests/test_provider_factory.py`
    # for the equivalent done by constructing `Settings` directly instead).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    result = runner.invoke(
        app, ["run", "configs/study.demo.yaml", "--provider", "anthropic"]
    )
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_run_with_report_flag_also_writes_report_files(
    fresh_db: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            "configs/study.demo.yaml",
            "--report",
            "--out-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "study_1_report.md").exists()
    assert (out_dir / "study_1_report.html").exists()
    assert "study_1_report.md" in result.output


def test_run_is_resumable_without_duplicate_runs(fresh_db: Path) -> None:
    """PROJECT_SPEC.md §M4's own resumability contract, exercised through the
    CLI: running the same materialised study twice does not duplicate work.
    Since `sul run` re-materialises on every invocation (a fresh `Study`
    row each time, per `materialize_study`'s own docstring: "Not idempotent
    -- calling this twice... creates a second, independent study"), this
    instead re-runs the *same already-materialised* study directly through
    the runner to prove idempotence at `run_study`'s own level -- the
    contract `sul run` depends on, not something it re-implements.
    """
    import asyncio

    from sul.db import create_all, make_engine, make_session_factory
    from sul.providers.fake import FakeProvider
    from sul.runner.config import load_study_config, materialize_study
    from sul.runner.orchestrator import run_study

    settings = get_settings()
    engine = make_engine(settings.database_url)
    create_all(engine)
    session_factory = make_session_factory(engine)
    config = load_study_config("configs/study.demo.yaml")
    with session_factory() as session:
        materialized = materialize_study(session, config, base_path=Path.cwd())
        session.commit()

    async def _run_twice() -> tuple[int, int]:
        first = await run_study(
            session_factory,
            study_id=materialized.study_id,
            scenario_id=materialized.scenario_id,
            provider=FakeProvider(),
            provider_name="fake",
            model="fake-1",
        )
        second = await run_study(
            session_factory,
            study_id=materialized.study_id,
            scenario_id=materialized.scenario_id,
            provider=FakeProvider(),
            provider_name="fake",
            model="fake-1",
        )
        return len(first.completed), second.already_completed

    completed_first, already_completed_second = asyncio.run(_run_twice())
    assert completed_first == 6
    assert already_completed_second == 6

    from sqlalchemy import func, select

    from sul.models import Run

    with session_factory() as session:
        run_count = session.execute(
            select(func.count(Run.id)).where(Run.study_id == materialized.study_id)
        ).scalar_one()
    assert run_count == 6  # not 12 -- no duplicate Run rows
