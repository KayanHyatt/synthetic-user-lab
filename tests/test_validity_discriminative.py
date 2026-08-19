"""PROJECT_SPEC.md §M6.2. `is_material_difference` is tested against
hand-built counts (the negative control: it must say "no" for two identical
counts and "yes" for a deliberately large, real gap) independently of any
provider. The FakeProvider integration test only proves the two-artefact
pipeline runs end to end offline without error -- per the M6 design
conversation, it must NOT assert a direction for `material_difference`,
since FakeProvider's category draws are content-blind and any observed gap
would be sampling noise, not evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.providers.fake import FakeProvider
from sul.validity.discriminative import (
    is_material_difference,
    run_discriminative_validity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_is_material_difference_says_no_for_identical_counts() -> None:
    assert is_material_difference(3, 3) is False
    assert is_material_difference(0, 0) is False


def test_is_material_difference_detects_a_real_gap() -> None:
    """Negative control: a fixture where the bad artefact's count is
    obviously, deliberately worse must be flagged -- if this ever returned
    False here, the rule would be structurally incapable of ever passing,
    which is exactly the "can only fail" mirror image of the "can only pass"
    failure mode this milestone exists to prevent.
    """
    assert is_material_difference(6, 1) is True


def test_is_material_difference_rejects_a_small_absolute_gap() -> None:
    """A 1-vs-0 count is a 'material' ratio but not a material absolute
    difference at this panel's size -- the rule must not fire on it.
    """
    assert is_material_difference(1, 0) is False


@pytest.mark.asyncio
async def test_fakeprovider_runs_both_artefacts_end_to_end_offline(
    session_factory: sessionmaker[Session],
) -> None:
    result = await run_discriminative_validity(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    assert result.bad_blocker_confusion_count >= 0
    assert result.good_blocker_confusion_count >= 0
