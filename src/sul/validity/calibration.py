"""PROJECT_SPEC.md §M6.5 ("Known-answer calibration", specified as recall
against a fixed known-answer set -- "Report detection rate", not a confidence
score; see the M6 implementation note in PROJECT_SPEC.md for the header/body
naming mismatch).

Matching is deliberately conservative: a defect counts as detected only if a
`Finding`'s summary-or-evidence text contains at least one keyword from
*every* one of that defect's keyword groups (never just one keyword total).
A single-keyword matcher would eventually fire on FakeProvider's synthesized
findings by pure chance across enough runs; requiring a co-occurrence of two
independent concept groups (the affected thing, and what's wrong with it)
does not. `tests/test_validity_calibration.py` proves both directions: a
hand-built, unambiguous finding is detected, and `FakeProvider`'s actual
random-letter summaries are not.
"""

from __future__ import annotations

from dataclasses import dataclass

from sul.analysis.clustering import FindingRow
from sul.validity.model import DefectResult


@dataclass(frozen=True)
class DefectSpec:
    defect_id: str
    description: str
    keyword_groups: tuple[frozenset[str], ...]


BAD_ONBOARDING_DEFECTS: tuple[DefectSpec, ...] = (
    DefectSpec(
        defect_id="missing-email-label",
        description=(
            "The required 'Work email' field has no visible label or placeholder text."
        ),
        keyword_groups=(
            frozenset({"email"}),
            frozenset(
                {
                    "label",
                    "unlabeled",
                    "unlabelled",
                    "no label",
                    "what field",
                    "unclear",
                }
            ),
        ),
    ),
    DefectSpec(
        defect_id="dead-plan-details-link",
        description="The 'See full plan details' link is a dead anchor (href=\"#\").",
        keyword_groups=(
            frozenset({"link", "plan details", "details link"}),
            frozenset(
                {
                    "dead",
                    "nothing",
                    "nowhere",
                    "broken",
                    "not work",
                    "didn't work",
                    "doesn't work",
                    "goes nowhere",
                }
            ),
        ),
    ),
    DefectSpec(
        defect_id="price-contradiction",
        description=(
            "The headline price ($9/mo) contradicts the pricing table ($15/mo)."
        ),
        keyword_groups=(
            frozenset({"price", "pricing", "$9", "$15", "cost"}),
            frozenset(
                {
                    "contradict",
                    "mismatch",
                    "different",
                    "match",
                    "wrong",
                    "inconsistent",
                    "didn't match",
                    "doesn't match",
                }
            ),
        ),
    ),
)


def _text_for_matching(row: FindingRow) -> str:
    return f"{row.summary} {row.evidence_content}".lower()


def defect_detected(defect: DefectSpec, rows: list[FindingRow]) -> bool:
    return any(
        all(any(kw in text for kw in group) for group in defect.keyword_groups)
        for text in (_text_for_matching(row) for row in rows)
    )


@dataclass(frozen=True)
class KnownAnswerCalibrationResult:
    per_defect: list[DefectResult]
    detected_count: int
    total_defects: int
    detection_rate: float


def measure_known_answer_calibration(
    rows: list[FindingRow], defects: tuple[DefectSpec, ...] = BAD_ONBOARDING_DEFECTS
) -> KnownAnswerCalibrationResult:
    per_defect = [
        DefectResult(
            defect_id=d.defect_id,
            description=d.description,
            detected=defect_detected(d, rows),
        )
        for d in defects
    ]
    detected_count = sum(1 for r in per_defect if r.detected)
    return KnownAnswerCalibrationResult(
        per_defect=per_defect,
        detected_count=detected_count,
        total_defects=len(defects),
        detection_rate=detected_count / len(defects) if defects else 0.0,
    )


__all__ = [
    "BAD_ONBOARDING_DEFECTS",
    "DefectSpec",
    "KnownAnswerCalibrationResult",
    "defect_detected",
    "measure_known_answer_calibration",
]
