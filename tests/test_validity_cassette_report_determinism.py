"""PROJECT_SPEC.md §M6 Deviation 13 / amended Deviation 5: the test that
should have existed before `tests/cassettes/`'s 46 real cassettes (Config A
-- Deviation 12) were committed. Two claims, both checked here, offline,
against `sul validate` itself:

1. `sul validate`'s own committed output, `docs/validity_report.md`, is
   reproducible from what's actually committed in the repo (the cassettes),
   not a one-off transcript of a run that happened once and was then
   hand-pasted in -- the same "committed generated file" discipline §M6
   Deviation 6 already holds `docs/validity_report.md` to, now genuinely
   exercised against a real provider's replayed traffic instead of only
   `FakeProvider`.
2. §M6.2-.5's four gated sections come back `MEASURED` in that output, not
   `NOT_MEASURED_OFFLINE` -- proving the cassette-replay fix (Deviation 13)
   actually unblocks real measurement in the command a user actually runs,
   not just in a side script.

Mirrors `tests/test_report_determinism.py`'s cross-process pattern exactly,
for the same reason that file gives: a same-process "render twice" check
cannot catch a wall-clock/iteration-order defect, and §M6.2's discriminative-
validity check clusters real Analyst findings from these cassettes -- the
same clustering code `sul.analysis.clustering`'s module docstring documents
as order-sensitive.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "support" / "run_sul_validate_script.py"
COMMITTED_REPORT = Path(__file__).resolve().parents[1] / "docs" / "validity_report.md"


def _run_script(*, pythonhashseed: str) -> dict[str, object]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = pythonhashseed
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload: dict[str, object] = json.loads(result.stdout.strip())
    return payload


def test_sul_validate_reproduces_the_committed_report_from_committed_cassettes() -> (
    None
):
    first = _run_script(pythonhashseed="0")
    second = _run_script(pythonhashseed="1")

    # Cross-process byte-stability first -- same pattern as
    # test_report_determinism.py, checked before comparing against the
    # committed file so a determinism regression is never mistaken for a
    # stale golden file.
    assert first == second

    committed = COMMITTED_REPORT.read_text(encoding="utf-8")
    assert first["markdown"] == committed


def test_the_four_gated_sections_are_measured_not_offline() -> None:
    payload = _run_script(pythonhashseed="0")
    markdown = payload["markdown"]
    assert isinstance(markdown, str)
    assert "NOT MEASURED OFFLINE" not in markdown, (
        "sul validate has real cassettes to replay (tests/cassettes/) but "
        "still reported a gated section -- the cassette-backed path "
        "(§M6 Deviation 5, amended) did not actually run"
    )
