"""`sul personas sample <panel.yaml>` (PROJECT_SPEC.md §M7). Prints only --
no database write; §M3's own acceptance criterion (byte-identical output
across two runs given the same seed) is checked directly against stdout.
"""

from __future__ import annotations

from typer.testing import CliRunner

from sul.cli import app

runner = CliRunner()


def test_sample_prints_seed_size_and_every_persona_card() -> None:
    result = runner.invoke(app, ["personas", "sample", "tests/fixtures/panel_1.yaml"])
    assert result.exit_code == 0, result.output
    assert "seed=" in result.output
    assert "size=" in result.output
    assert "card_template=" in result.output
    assert "persona 0" in result.output


def test_sample_output_is_byte_identical_across_two_invocations() -> None:
    first = runner.invoke(app, ["personas", "sample", "configs/panel.demo.yaml"])
    second = runner.invoke(app, ["personas", "sample", "configs/panel.demo.yaml"])
    assert first.exit_code == second.exit_code == 0
    assert first.output == second.output


def test_sample_writes_nothing_to_the_database(tmp_path, monkeypatch) -> None:
    """The acceptance criterion is stdout, not a side effect: pointing
    `SUL_DATABASE_URL` at a not-yet-existing file and confirming it still
    doesn't exist after the command runs proves this command never opens a
    database connection at all.
    """
    from sul.config import get_settings

    db_path = tmp_path / "sul.db"
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()

    result = runner.invoke(app, ["personas", "sample", "configs/panel.demo.yaml"])
    assert result.exit_code == 0, result.output
    assert not db_path.exists()


def test_sample_reports_realised_segment_proportions() -> None:
    result = runner.invoke(app, ["personas", "sample", "configs/panel.demo.yaml"])
    assert result.exit_code == 0, result.output
    assert "segment time_poor_professional" in result.output
    assert "segment cost_sensitive_student" in result.output
