"""`sul validate` (PROJECT_SPEC.md §M6's own acceptance criterion). Points
`SUL_DATABASE_URL` at a path that does not exist yet -- not a pre-created,
`create_all`'d database file -- because `sul validate` is the first CLI
command in this project that can be the very first thing run against a fresh
clone (`sul cost`/`sul report` both require a study that some earlier command
already created). An earlier version of this fixture called `create_all`
itself, which masked a real bug: `validate()` didn't call `create_all` and
failed against a genuinely fresh database (caught by running `make.ps1
validate` for real, not by this suite).

The second test is the structural enforcement Confirm 1 in the M6 design
conversation asked for: `sul validate` must have no flag that could point it
at anything but `FakeProvider` -- checked against the command's actual
`--help` output, not asserted in a comment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sul.cli import app
from sul.config import get_settings

runner = CliRunner()


@pytest.fixture
def fresh_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "sul.db"
    assert not db_path.exists()
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    return db_path


def test_sul_validate_writes_both_files_end_to_end_offline(
    fresh_db_path: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "docs"
    result = runner.invoke(app, ["validate", "--out-dir", str(out_dir)])

    assert result.exit_code == 0, result.output
    validity_path = out_dir / "validity_report.md"
    limitations_path = out_dir / "limitations.md"
    assert validity_path.exists()
    assert limitations_path.exists()
    assert str(validity_path) in result.output
    assert str(limitations_path) in result.output

    validity_text = validity_path.read_text(encoding="utf-8")
    assert validity_text.count("NOT MEASURED OFFLINE") == 4

    limitations_text = limitations_path.read_text(encoding="utf-8")
    assert "not counted toward the two measured weaknesses" in limitations_text


def test_sul_validate_has_no_flag_to_select_a_different_provider(
    fresh_db_path: Path,
) -> None:
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0, result.output
    for forbidden in ("--provider", "--cassette", "--record", "--model"):
        assert forbidden not in result.output, (
            f"sul validate must never expose {forbidden!r} -- it always "
            "runs FakeProvider (PROJECT_SPEC.md §M6: offline end to end)"
        )
