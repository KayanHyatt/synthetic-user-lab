"""`sul validate` (PROJECT_SPEC.md §M6's own acceptance criterion). Points
`SUL_DATABASE_URL` at a path that does not exist yet -- not a pre-created,
`create_all`'d database file -- because `sul validate` is the first CLI
command in this project that can be the very first thing run against a fresh
clone (`sul cost`/`sul report` both require a study that some earlier command
already created). An earlier version of this fixture called `create_all`
itself, which masked a real bug: `validate()` didn't call `create_all` and
failed against a genuinely fresh database (caught by running `make.ps1
validate` for real, not by this suite).

`sul validate`'s provider is no longer always `FakeProvider` (PROJECT_SPEC.md
§M6 Deviation 5, amended): it picks up `tests/cassettes/`'s real, committed
recording when present, falling back to `FakeProvider` only when that
directory is empty. `test_sul_validate_falls_back_to_fakeprovider_when_no_
cassettes_exist` below forces the empty-directory branch explicitly (via
`SUL_CASSETTE_DIR`), so its offline-gated assertions hold regardless of
whether `tests/cassettes/` happens to be populated at test-run time --
the real, cassette-backed branch (default `tests/cassettes/`, unmodified) is
exercised end-to-end, byte-for-byte against the committed report, by
`tests/test_validity_cassette_report_determinism.py` instead; this file
stays about `sul validate`'s own CLI-level contract.

The second test is the structural enforcement Confirm 1 in the M6 design
conversation asked for: `sul validate` must have no flag that could select a
provider directly -- checked against the command's actual `--help` output,
not asserted in a comment. It is still true after the amendment: the choice
between `FakeProvider` and a cassette-backed `AnthropicProvider` is made
automatically, by `_select_validate_provider`, from cassette-directory
contents alone, never from a command-line flag.
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


@pytest.fixture
def empty_cassette_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Forces `_select_validate_provider`'s `FakeProvider` fallback branch,
    independent of whether the real `tests/cassettes/` happens to be
    populated -- a test asserting offline-gated behaviour must not depend on
    that.
    """
    cassette_dir = tmp_path / "empty_cassettes"
    cassette_dir.mkdir()
    monkeypatch.setenv("SUL_CASSETTE_DIR", str(cassette_dir))
    get_settings.cache_clear()
    return cassette_dir


def test_sul_validate_falls_back_to_fakeprovider_when_no_cassettes_exist(
    fresh_db_path: Path, empty_cassette_dir: Path, tmp_path: Path
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
    # Once in the summary table (per-row provenance), once in the detailed
    # section, for each of the four gated checks.
    assert validity_text.count("NOT MEASURED OFFLINE") == 8

    limitations_text = limitations_path.read_text(encoding="utf-8")
    assert "not counted toward the two measured weaknesses" in limitations_text


def test_sul_validate_uses_committed_cassettes_when_present(
    fresh_db_path: Path, tmp_path: Path
) -> None:
    """The real, default `tests/cassettes/` (46 committed cassettes,
    PROJECT_SPEC.md §M6 Deviation 12/13) is left unmodified here -- this is
    a quick CLI-level smoke check that the cassette-backed branch actually
    fires by default; `tests/test_validity_cassette_report_determinism.py`
    is the exhaustive, byte-for-byte version of this same claim.
    """
    out_dir = tmp_path / "docs"
    result = runner.invoke(app, ["validate", "--out-dir", str(out_dir)])

    assert result.exit_code == 0, result.output
    validity_text = (out_dir / "validity_report.md").read_text(encoding="utf-8")
    assert "NOT MEASURED OFFLINE" not in validity_text
    assert "anthropic/claude-sonnet-5" in validity_text


def test_sul_validate_has_no_flag_to_select_a_different_provider(
    fresh_db_path: Path,
) -> None:
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0, result.output
    for forbidden in ("--provider", "--cassette", "--record", "--model"):
        assert forbidden not in result.output, (
            f"sul validate must never expose {forbidden!r} -- the choice "
            "between FakeProvider and a cassette-backed AnthropicProvider "
            "is automatic, from cassette-directory contents alone "
            "(PROJECT_SPEC.md §M6 Deviation 5, amended), never user-selected"
        )
