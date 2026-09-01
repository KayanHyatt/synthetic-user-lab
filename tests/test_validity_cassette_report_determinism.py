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

    # Explicit, not incidental: before this assertion existed, a missing or
    # failing Config A cassette was only *likely* to be caught, as a side
    # effect of the byte-comparison below failing for some other reason --
    # never checked directly. See run_sul_validate_script.py's own
    # docstring: a "measured" section status (test below) does not by
    # itself prove every dispatch this run needed actually succeeded.
    assert first["failed_run_count"] == 0, (
        f"a Run failed during sul validate's own Config A replay: "
        f"{first['failed_run_errors']}"
    )

    committed = COMMITTED_REPORT.read_text(encoding="utf-8")
    assert first["markdown"] == committed


def test_the_four_gated_sections_are_measured_not_offline() -> None:
    payload = _run_script(pythonhashseed="0")
    assert payload["failed_run_count"] == 0, (
        f"a Run failed during sul validate's own Config A replay: "
        f"{payload['failed_run_errors']}"
    )
    markdown = payload["markdown"]
    assert isinstance(markdown, str)
    assert "NOT MEASURED OFFLINE" not in markdown, (
        "sul validate has real cassettes to replay (tests/cassettes/) but "
        "still reported a gated section -- the cassette-backed path "
        "(§M6 Deviation 5, amended) did not actually run"
    )


# ---------------------------------------------------------------------------
# Config B (PROJECT_SPEC.md §M6 Deviation 18): extends this file rather than
# tests/test_validity_cassette_plumbing.py. That file proves the record/
# replay *mechanism* works at all, against a single hand-authored
# MockTransport response written to an isolated tmp_path -- never real
# committed cassettes, never the full harness. This is the opposite kind of
# claim: that the 10 real, committed Config B cassettes replay through
# run_validity_harness end to end and produce specific, reproducible
# numbers -- exactly what the two tests above already prove for Config A,
# just reached by calling run_validity_harness directly instead of through
# `sul validate`, since `sul.cli._select_validate_provider` always requests
# Config A's own model combination and structurally cannot reach Config B.
# The order-sensitivity risk this file's own module docstring names
# (discriminative validity clusters real Analyst findings) applies
# identically to Config B's Analyst, so it gets the same cross-process,
# differing-PYTHONHASHSEED treatment as Config A above, not a single
# same-process call.
# ---------------------------------------------------------------------------

CONFIG_B_SCRIPT = (
    Path(__file__).resolve().parent
    / "support"
    / "run_config_b_validity_report_script.py"
)


def _run_config_b_script(*, pythonhashseed: str) -> dict[str, object]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = pythonhashseed
    result = subprocess.run(
        [sys.executable, str(CONFIG_B_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    payload: dict[str, object] = json.loads(result.stdout.strip())
    return payload


def test_config_b_numbers_are_reproducible_and_complete() -> None:
    """Cross-process determinism first (catches the same order-sensitivity
    class as the Config A tests above), then the actual values -- not just
    `MeasurementStatus`, and not a `MeasurementStatus` of `measured` alone
    either: verified by hand while building the script this drives (see its
    own docstring), a single missing Config B cassette still produced
    `measured` sections with unchanged headline numbers, because
    `_run_one_persona`'s per-run containment (§M7 Deviation 17) silently
    marks just the affected persona's `Run` `FAILED` and the section
    finishes on whatever remains. Only `failed_run_count == 0`, queried
    directly against every `Run` row this run wrote, actually proves the
    10 cassettes recorded at Deviation 18 are complete, not merely
    present.
    """
    first = _run_config_b_script(pythonhashseed="0")
    second = _run_config_b_script(pythonhashseed="1")
    assert first == second

    assert first["failed_run_count"] == 0, (
        f"a Run failed during a Config B replay that should be complete: "
        f"{first['failed_run_errors']}"
    )

    assert first["provider_name"] == "anthropic"
    assert first["model"] == "claude-haiku-4-5"

    disc = first["discriminative_validity"]
    assert isinstance(disc, dict)
    assert disc["status"] == "measured"
    assert disc["bad_blocker_confusion_count"] == 6
    assert disc["good_blocker_confusion_count"] == 0
    assert disc["material_difference"] is True
    assert disc["bad_personas_attempted"] == disc["bad_personas_completed"] == 5
    assert disc["good_personas_attempted"] == disc["good_personas_completed"] == 5
    assert {p["agent"] for p in disc["provenance"]} == {
        "analyst",
        "moderator",
        "persona",
    }
    assert all(p["model"] == "claude-haiku-4-5" for p in disc["provenance"])

    # PROJECT_SPEC.md §M6 Deviation 20: the aggregate above (6 vs 0) is
    # identical to Config A's, but the composition behind it is not --
    # Config A's committed docs/validity_report.md shows
    # `{blocker: 1, confusion: 5, missing_info: 2}` (5 distinct evidence
    # anchors) on the bad artefact; Config B's Haiku Analyst produces zero
    # `blocker` findings on the identical replayed transcript, reclassified
    # into `confusion` instead (1+5 = 0+6 = 6 either way), anchored to
    # fewer distinct positions.
    assert disc["bad_category_counts"] == {"confusion": 6, "missing_info": 1}
    assert disc["bad_distinct_anchor_count"] == 2
    assert disc["good_category_counts"] == {"delight": 5}
    assert disc["good_distinct_anchor_count"] == 1

    calib = first["known_answer_calibration"]
    assert isinstance(calib, dict)
    assert calib["status"] == "measured"
    assert calib["total_defects"] == 3
    assert calib["detected_count"] == 1
    assert calib["detection_rate"] == 1 / 3
    detected_ids = {d["defect_id"] for d in calib["per_defect"] if d["detected"]}
    assert detected_ids == {"missing-email-label"}

    acq = first["acquiescence_bias"]
    assert isinstance(acq, dict)
    assert acq["status"] == "measured"
    assert acq["subjects_measured"] == acq["subjects_attempted"] == 5
    assert acq["positive_agree_rate"] == 0.0
    assert acq["negative_agree_rate"] == 1.0
    assert acq["agreement_gap"] == 1.0

    pos = first["position_bias"]
    assert isinstance(pos, dict)
    assert pos["status"] == "measured"
    assert pos["subjects_measured"] == pos["subjects_attempted"] == 5
    assert pos["preference_shift"] == 0.0
