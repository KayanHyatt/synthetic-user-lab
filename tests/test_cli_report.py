"""`sul report <study_id>` (PROJECT_SPEC.md §M5's own acceptance criterion).
Uses a real on-disk SQLite file (not the in-memory `session` fixture) because
the CLI opens its own engine from `Settings.database_url`, the way a real
invocation would -- mirrors `test_cli_cost.py`'s `seeded_db` pattern.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sul.cli import app
from sul.config import get_settings
from sul.db import create_all, make_engine, make_session_factory
from tests.support.report_factory import build_report_fixture

runner = CliRunner()


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, int]:
    db_path = tmp_path / "sul.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        fixture = build_report_fixture(session)
        study_id = fixture.study_id
    engine.dispose()

    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    return db_path, study_id


def test_sul_report_writes_both_formats_to_deterministic_paths(
    seeded_db: tuple[Path, int], tmp_path: Path
) -> None:
    _db_path, study_id = seeded_db
    out_dir = tmp_path / "out"
    result = runner.invoke(app, ["report", str(study_id), "--out-dir", str(out_dir)])

    assert result.exit_code == 0, result.output
    md_path = out_dir / f"study_{study_id}_report.md"
    html_path = out_dir / f"study_{study_id}_report.html"
    assert md_path.exists()
    assert html_path.exists()
    assert str(md_path) in result.output
    assert str(html_path) in result.output
    assert "submit button" in md_path.read_text(encoding="utf-8")


def test_sul_report_unknown_study_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "empty.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    engine.dispose()

    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()

    result = runner.invoke(
        app, ["report", "999999", "--out-dir", str(tmp_path / "out")]
    )
    assert result.exit_code != 0


def test_sul_report_include_failed_flag_changes_denominator(
    seeded_db: tuple[Path, int], tmp_path: Path
) -> None:
    _db_path, study_id = seeded_db
    out_dir = tmp_path / "out"
    default_result = runner.invoke(
        app, ["report", str(study_id), "--out-dir", str(out_dir / "default")]
    )
    included_result = runner.invoke(
        app,
        [
            "report",
            str(study_id),
            "--out-dir",
            str(out_dir / "included"),
            "--include-failed",
        ],
    )
    assert default_result.exit_code == 0
    assert included_result.exit_code == 0

    default_md = (out_dir / "default" / f"study_{study_id}_report.md").read_text(
        encoding="utf-8"
    )
    included_md = (out_dir / "included" / f"study_{study_id}_report.md").read_text(
        encoding="utf-8"
    )
    # Default denominator is 3 (Ana, Ben, Cid); --include-failed adds Dee -> 4.
    assert "denominator for every fraction below): 3" in default_md
    assert "denominator for every fraction below): 4" in included_md


def test_sul_report_does_not_modify_the_database_file(
    seeded_db: tuple[Path, int], tmp_path: Path
) -> None:
    """`sul report` is a read-only command (§8 deviation: `Finding.cluster_id`
    is never persisted). Hashing the database file before and after is a
    stronger check than inspecting one column -- it catches any write, not
    just the one write we already decided against.
    """
    db_path, study_id = seeded_db
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    result = runner.invoke(
        app, ["report", str(study_id), "--out-dir", str(tmp_path / "out")]
    )
    assert result.exit_code == 0, result.output

    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert before == after
