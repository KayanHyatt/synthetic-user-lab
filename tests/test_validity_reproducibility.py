"""PROJECT_SPEC.md §M6.1. Two things are tested separately on purpose:

1. The *statistic* (`jaccard`/`mean_top5_jaccard`/variance) against hand-built
   synthetic repeats with a known, deliberate difference -- the negative
   control that proves these functions would report non-zero variance /
   sub-1.0 Jaccard if the pipeline really were non-reproducible, rather than
   being unable to detect that even in principle.
2. The real pipeline (`measure_reproducibility`, `FakeProvider`) against the
   documented offline baseline: exactly zero variance, exactly 1.0 Jaccard,
   every time -- because that is what `FakeProvider`'s deterministic hashing
   structurally guarantees (Correction 1 in the M6 design conversation), not
   evidence the panel itself is reproducible.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.analysis.clustering import FindingRow
from sul.analysis.config import ClusteringConfig
from sul.enums import FindingCategory
from sul.providers.fake import FakeProvider
from sul.validity.reproducibility import (
    jaccard,
    mean_top5_jaccard,
    measure_reproducibility,
    top5_content_key_sets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _row(
    finding_id: int, persona: str, summary: str, *, severity: int = 3
) -> FindingRow:
    return FindingRow(
        finding_id=finding_id,
        run_id=finding_id,
        persona_id=hash(persona) % 1000,
        persona_name=persona,
        segment="seg",
        category=FindingCategory.BLOCKER,
        severity=severity,
        summary=summary,
        evidence_turn_id=finding_id,
        evidence_content="evidence",
        evidence_turn_ordinal=1,
    )


def test_jaccard_is_one_for_identical_sets_and_less_for_disjoint_sets() -> None:
    a = frozenset({("Ana", "blocker", "x"), ("Ben", "blocker", "y")})
    assert jaccard(a, a) == 1.0
    b = frozenset({("Cid", "trust", "z")})
    assert jaccard(a, b) == 0.0
    c = frozenset({("Ana", "blocker", "x"), ("Cid", "trust", "z")})
    assert 0.0 < jaccard(a, c) < 1.0


def test_mean_top5_jaccard_detects_a_real_difference_between_repeats() -> None:
    """Negative control: two synthetic "repeats" whose top clusters
    deliberately don't match. If this ever reported 1.0, the statistic would
    be structurally incapable of catching non-reproducibility -- exactly the
    failure mode PROJECT_SPEC.md's "unreported variance is not [fine]" line
    warns about.
    """
    repeat_a = [frozenset({("Ana", "blocker", "same finding")})]
    repeat_b = [frozenset({("Ana", "blocker", "a completely different finding")})]
    assert mean_top5_jaccard([repeat_a, repeat_b]) == 0.0

    identical_a = [frozenset({("Ana", "blocker", "same finding")})]
    identical_b = [frozenset({("Ana", "blocker", "same finding")})]
    assert mean_top5_jaccard([identical_a, identical_b]) == 1.0


def test_top5_content_key_sets_ranks_by_frequency_times_severity() -> None:
    """A synthetic corpus with two clearly-separated clusters (by summary
    vocabulary) -- the higher-frequency, higher-severity cluster must rank
    first, proving the ranking/content-key plumbing (not just the raw
    clustering) is exercised, not bypassed.
    """
    rows = [
        _row(1, "Ana", "could not find the submit button on the form", severity=5),
        _row(2, "Ben", "could not find the submit button on the form", severity=5),
        _row(3, "Cid", "the color scheme felt a little dated", severity=1),
    ]
    config = ClusteringConfig()
    top5 = top5_content_key_sets(rows, config)
    assert len(top5) == 2
    assert len(top5[0]) == 2  # the submit-button cluster: two personas
    assert len(top5[1]) == 1  # the color-scheme singleton


@pytest.mark.asyncio
async def test_fakeprovider_same_seed_repeats_are_exactly_reproducible(
    session_factory: sessionmaker[Session],
) -> None:
    section = await measure_reproducibility(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        repeats=2,
        seed_sensitivity_seeds=2,
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    assert section.finding_count_variance == 0.0
    assert section.mean_top5_cluster_jaccard == 1.0
    assert "structurally guaranteed" in section.caveat
