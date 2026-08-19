"""PROJECT_SPEC.md §M6.2: run the panel on `good_onboarding.html` and
`bad_onboarding.html`; the bad artefact must produce materially more
`blocker`/`confusion` findings.

This module's public function always actually runs both studies and computes
real numbers, regardless of which provider it's given -- there is no
FakeProvider-specific branch here (per the M6 design conversation, Confirm 1:
"no branch that only exists for the fake"). Whether those numbers are worth
showing a reader is a judgement `sul.validity.harness` makes once, centrally,
based on `provider_name` -- not something this module decides about itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.analysis.clustering import FindingRow
from sul.enums import FindingCategory
from sul.providers.base import LLMProvider
from sul.validity.runs import run_artefact_study

DEFAULT_BAD_ARTEFACT_PATH = "artefacts/bad_onboarding.html"
DEFAULT_GOOD_ARTEFACT_PATH = "artefacts/good_onboarding.html"
DEFAULT_PANEL_PATH = "configs/panel_validity.yaml"

_DISCRIMINATIVE_CATEGORIES = (FindingCategory.BLOCKER, FindingCategory.CONFUSION)


def blocker_confusion_count(rows: list[FindingRow]) -> int:
    return sum(1 for r in rows if r.category in _DISCRIMINATIVE_CATEGORIES)


def is_material_difference(bad_count: int, good_count: int) -> bool:
    """The threshold rule §M6.2 leaves unspecified: the bad artefact's
    blocker/confusion count must be at least 1.5x the good artefact's *and*
    at least 2 findings more in absolute terms -- the ratio alone would call
    a 1-vs-0 count "material", which is noise, not signal, at this panel
    size.
    """
    return bad_count >= good_count * 1.5 and (bad_count - good_count) >= 2


@dataclass(frozen=True)
class DiscriminativeValidityResult:
    bad_rows: list[FindingRow]
    good_rows: list[FindingRow]
    bad_blocker_confusion_count: int
    good_blocker_confusion_count: int
    material_difference: bool


async def run_discriminative_validity(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    bad_artefact_path: str = DEFAULT_BAD_ARTEFACT_PATH,
    good_artefact_path: str = DEFAULT_GOOD_ARTEFACT_PATH,
    panel_path: str = DEFAULT_PANEL_PATH,
    base_path: Path | None = None,
) -> DiscriminativeValidityResult:
    root = base_path if base_path is not None else Path.cwd()

    bad_rows = await run_artefact_study(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        artefact_path=bad_artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.2 discriminative validity: bad artefact",
    )
    good_rows = await run_artefact_study(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        artefact_path=good_artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.2 discriminative validity: good artefact",
    )

    bad_count = blocker_confusion_count(bad_rows)
    good_count = blocker_confusion_count(good_rows)

    return DiscriminativeValidityResult(
        bad_rows=bad_rows,
        good_rows=good_rows,
        bad_blocker_confusion_count=bad_count,
        good_blocker_confusion_count=good_count,
        material_difference=is_material_difference(bad_count, good_count),
    )


__all__ = [
    "DEFAULT_BAD_ARTEFACT_PATH",
    "DEFAULT_GOOD_ARTEFACT_PATH",
    "DEFAULT_PANEL_PATH",
    "DiscriminativeValidityResult",
    "blocker_confusion_count",
    "is_material_difference",
    "run_discriminative_validity",
]
