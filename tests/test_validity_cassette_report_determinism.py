"""PROJECT_SPEC.md §M6 Deviation 13: the test that should have existed
before `tests/cassettes/`'s 46 real cassettes (Config A -- Deviation 12)
were committed. Two claims, both checked here, offline:

1. Replaying all 46 cassettes reproduces `docs/validity_report_recorded.md`
   byte-for-byte -- so `make validate`'s committed-generated-file discipline
   (§M6 Deviation 6) extends to this file too: it is not a one-off transcript
   of a run that happened once, it is reproducible from what's actually
   committed in the repo, the same way `docs/validity_report.md` is
   reproducible from `FakeProvider`.
2. §M6.2-.5's four gated sections come back `MEASURED` against it, not
   `NOT_MEASURED_OFFLINE`/`PARTIALLY_MEASURED` -- proving the cassette
   fix (Deviation 13) actually unblocks real measurement, not just "replay
   no longer raises."

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

SCRIPT = (
    Path(__file__).resolve().parent
    / "support"
    / "run_recorded_validity_report_script.py"
)
COMMITTED_REPORT = (
    Path(__file__).resolve().parents[1] / "docs" / "validity_report_recorded.md"
)


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


def test_replaying_the_committed_cassettes_reproduces_the_committed_report() -> None:
    first = _run_script(pythonhashseed="0")
    second = _run_script(pythonhashseed="1")

    # Cross-process byte-stability first -- same pattern as
    # test_report_determinism.py, checked before comparing against the
    # committed file so a determinism regression is never mistaken for a
    # stale golden file.
    assert first == second

    committed = COMMITTED_REPORT.read_text(encoding="utf-8")
    assert first["markdown"] == committed


def test_the_four_gated_sections_are_measured_against_real_cassettes() -> None:
    payload = _run_script(pythonhashseed="0")
    statuses = payload["statuses"]
    assert isinstance(statuses, dict)
    for name in (
        "discriminative_validity",
        "acquiescence_bias",
        "position_bias",
        "known_answer_calibration",
    ):
        assert statuses[name] == "measured", (
            f"{name} was {statuses[name]!r}, not 'measured' -- the cassette "
            "replay fix (§M6 Deviation 13) is supposed to unblock exactly this"
        )
