"""PROJECT_SPEC.md §M6 Deviation 19: `DiscriminativeValiditySection` (and
`KnownAnswerCalibrationSection`, which reads the same rows) carried no
completion denominator, unlike `AcquiescenceSection`/`PositionBiasSection`,
which both carry `subjects_attempted`/`subjects_measured` precisely so
`PARTIALLY_MEASURED` can fire when a subject drops out. Since §M7 Deviation
17, a persona whose turn-loop run fails is contained *per-run*, inside
`_run_one_persona`, and never reaches `run_validity_harness`'s own
section-level `except (ProviderError, StructuredOutputError)` -- so a
missing or failing cassette used to leave this section reporting a
confident integer over fewer personas than it actually attempted, with
nothing to signal it.

This is the negative control for that fix: a real, committed cassette
directory, copied to `tmp_path` (never the committed `tests/cassettes/`
itself -- nothing here mutates it), with exactly one required file removed
-- the Sonnet Analyst dispatch for the one bad-artefact persona whose
transcript escalated across four turns (PROJECT_SPEC.md §M6 Deviation 18's
own finding-row comparison: `felt stuck and unable to proceed` is that
persona's `blocker` finding). Removing it makes that persona's `Run` fail
with a contained `CassetteMissError` (surfaced as a generic `ProviderError`
-- see `tests/support/run_config_b_validity_report_script.py`'s own
docstring for why the original message doesn't survive), leaving 4 of 5
bad-artefact personas completed.

Before this deviation's fix, this test's real assertions were false: the
section returned `MEASURED` with `bad_blocker_confusion_count` still a
confident (if now-wrong) integer, no denominator, no signal that a persona
had dropped out at all.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.providers.anthropic import AnthropicProvider
from sul.providers.cassette import CassetteTransport
from sul.validity.harness import run_validity_harness
from sul.validity.sentinel import MeasurementStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CASSETTE_DIR = REPO_ROOT / "tests" / "cassettes"

# The Sonnet Analyst dispatch for the bad-artefact persona whose escalating
# transcript produces four findings across turns 1/3/5/7, including the one
# `blocker` finding in the whole committed set -- identified by grepping the
# committed cassettes for that finding's own summary text, not guessed.
_REQUIRED_FILE = "bcb471b64818647f044a819d00a726fd581341fad2da1766c08522fc743fb05c.json"

_MODEL = "claude-haiku-4-5"
_ANALYST_MODEL = "claude-sonnet-5"


@pytest.mark.asyncio
async def test_a_missing_analyst_cassette_degrades_to_partially_measured(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    cassette_copy = tmp_path / "cassettes"
    shutil.copytree(REAL_CASSETTE_DIR, cassette_copy)

    missing = cassette_copy / _REQUIRED_FILE
    assert missing.exists(), (
        f"{_REQUIRED_FILE} not found in the committed cassette set -- this "
        "test's own precondition (a real, required file) no longer holds"
    )
    missing.unlink()

    # Never touched: the copy is what gets mutated and read.
    assert (REAL_CASSETTE_DIR / _REQUIRED_FILE).exists()

    transport = CassetteTransport(
        httpx.AsyncHTTPTransport(), cassette_copy, record=False
    )
    provider = AnthropicProvider(
        "sul-completeness-test-replay-only-sentinel-key", transport=transport
    )

    report = await run_validity_harness(
        session_factory,
        provider=provider,
        provider_name="anthropic",
        model=_MODEL,
        model_by_agent={AgentRole.ANALYST: _ANALYST_MODEL},
        base_path=REPO_ROOT,
    )

    disc = report.discriminative_validity
    assert disc.status == MeasurementStatus.PARTIALLY_MEASURED, (
        f"expected PARTIALLY_MEASURED with one bad-artefact persona missing "
        f"its Analyst dispatch, got {disc.status!r} "
        f"(bad_blocker_confusion_count={disc.bad_blocker_confusion_count!r})"
    )
    assert disc.reason is not None and "bad" in disc.reason.lower()
    assert disc.bad_personas_attempted == 5
    assert disc.bad_personas_completed == 4
    assert disc.good_personas_attempted == 5
    assert disc.good_personas_completed == 5

    calib = report.known_answer_calibration
    assert calib.status == MeasurementStatus.PARTIALLY_MEASURED
    assert calib.personas_attempted == 5
    assert calib.personas_completed == 4
