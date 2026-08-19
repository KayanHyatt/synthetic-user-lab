"""PROJECT_SPEC.md §M6.5. Two negative controls, paired deliberately (per the
M6 design conversation): the matcher must catch an unambiguous hand-built
finding (6.5a) *and* must not fire on `FakeProvider`'s actual random-letter
output (6.5c) -- run together so the matcher can't be tuned to pass one by
breaking the other (a matcher loose enough to hit noise would trivially also
"pass" 6.5a; a matcher so strict it never fires on anything would trivially
"pass" 6.5c).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.analysis.clustering import FindingRow
from sul.enums import FindingCategory
from sul.providers.fake import FakeProvider
from sul.validity.calibration import (
    BAD_ONBOARDING_DEFECTS,
    measure_known_answer_calibration,
)
from sul.validity.discriminative import run_discriminative_validity

REPO_ROOT = Path(__file__).resolve().parents[1]


def _row(summary: str, evidence: str = "") -> FindingRow:
    return FindingRow(
        finding_id=1,
        run_id=1,
        persona_id=1,
        persona_name="Ana",
        segment="seg",
        category=FindingCategory.MISSING_INFO,
        severity=3,
        summary=summary,
        evidence_turn_id=1,
        evidence_content=evidence,
        evidence_turn_ordinal=1,
    )


def test_unambiguous_hand_built_findings_are_all_detected() -> None:
    """6.5(a): a finding written to unambiguously describe each seeded
    defect must be detected as that defect.
    """
    rows = [
        _row("The work email field has no visible label explaining it."),
        _row("The 'see full plan details' link is dead and goes nowhere when clicked."),
        _row(
            "The headline price of $9/mo does not match the pricing table, which "
            "says $15/mo -- a clear contradiction."
        ),
    ]
    result = measure_known_answer_calibration(rows)
    assert result.detected_count == 3
    assert result.detection_rate == 1.0
    assert all(d.detected for d in result.per_defect)


def test_an_unrelated_finding_detects_nothing() -> None:
    rows = [_row("The color scheme felt a little dated to this persona.")]
    result = measure_known_answer_calibration(rows)
    assert result.detected_count == 0


@pytest.mark.asyncio
async def test_fakeprovider_random_letter_summaries_never_spuriously_match(
    session_factory: sessionmaker[Session],
) -> None:
    """6.5(c): the matcher must report 0/3 against `FakeProvider`'s actual
    synthesized output -- proof the matcher isn't loose enough to hallucinate
    a detection against gibberish (`FakeProvider._synthesize_word` draws
    4-12 random lowercase letters, not English).
    """
    result = await run_discriminative_validity(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    calibration = measure_known_answer_calibration(result.bad_rows)
    assert calibration.detected_count == 0
    assert calibration.total_defects == len(BAD_ONBOARDING_DEFECTS)
