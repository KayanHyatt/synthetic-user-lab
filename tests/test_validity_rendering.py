"""PROJECT_SPEC.md §M6: the `NOT_MEASURED_OFFLINE` sentinel must be visibly
distinct in rendered output, never a bare `None`/`0`/empty string standing in
for a real measurement (per the M6 design conversation). `docs/limitations.md`
must name at least two concrete, measured weaknesses (the acceptance
criterion), and must not count the four provider-gated checks toward that.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.providers.fake import FakeProvider
from sul.validity.harness import run_validity_harness
from sul.validity.limitations import render_limitations_markdown
from sul.validity.markdown import render_validity_markdown
from sul.validity.model import (
    AcquiescenceSection,
    AgentProvenance,
    ClusteringMarginMeasurement,
    DiscriminativeValiditySection,
    KnownAnswerCalibrationSection,
    PositionBiasSection,
    ReproducibilitySection,
    SeedSensitivitySection,
    ThresholdScalingMeasurement,
    ValidityReportModel,
    ZeroVectorConflationMeasurement,
)
from sul.validity.sentinel import MeasurementStatus

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_not_measured_offline_renders_distinctly_never_as_none_or_zero(
    session_factory: sessionmaker[Session],
) -> None:
    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )
    text = render_validity_markdown(report)

    # Once in the summary table, once in the detailed section, for each of
    # the four gated checks (the summary table was added for Task B in the
    # M6 design conversation, to carry per-row provenance).
    assert text.count("NOT MEASURED OFFLINE") == 8
    # None of the four gated sections' numeric fields print as bare "None".
    assert "material_difference: None" not in text
    assert "Material difference: None" not in text
    # The reproducibility section (always measured) is not gated.
    assert "Finding count variance: NOT MEASURED OFFLINE" not in text
    assert str(report.reproducibility.finding_count_variance) in text


@pytest.mark.asyncio
async def test_limitations_md_states_at_least_two_measured_weaknesses(
    session_factory: sessionmaker[Session],
) -> None:
    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )
    text = render_limitations_markdown(report)

    measured_weakness_headers = [
        "Cluster themes partly reflect the Analyst's writing style",
        "A rare theme and a broken measurement look identical",
        "Cluster granularity at a fixed threshold is unmeasured territory",
    ]
    present = [h for h in measured_weakness_headers if h in text]
    assert len(present) >= 2

    # The four provider-gated checks are named, but explicitly not counted.
    assert "not counted toward the two measured weaknesses" in text


def test_provenance_is_rendered_per_row_not_collapsed_to_one_value() -> None:
    """PROJECT_SPEC.md §M6, Task B in the design conversation: after a mixed
    run (reproducibility on FakeProvider, discriminative validity on a
    cassette-backed Sonnet Analyst + Haiku persona/moderator), the rendered
    report must show *both* configurations distinctly -- never one blanket
    provider/model value a reader could mistake for describing every row.
    Built by hand (not via `run_validity_harness`) so the two sections'
    provenance is deliberately, verifiably different, rather than hoping a
    real run happens to produce a mix.
    """
    report = ValidityReportModel(
        provider_name="anthropic",
        model="claude-sonnet-5",
        reproducibility=ReproducibilitySection(
            repeats=3,
            finding_count_variance=0.0,
            mean_top5_cluster_jaccard=1.0,
            seed_sensitivity=SeedSensitivitySection(
                seeds_tried=3,
                finding_count_range=(1, 1),
                cluster_count_range=(1, 1),
                mean_top5_cluster_jaccard=1.0,
            ),
            provenance=[
                AgentProvenance(agent="persona", provider="fake", model="fake-1"),
                AgentProvenance(agent="moderator", provider="fake", model="fake-1"),
                AgentProvenance(agent="analyst", provider="fake", model="fake-1"),
            ],
        ),
        discriminative_validity=DiscriminativeValiditySection(
            status=MeasurementStatus.MEASURED,
            bad_blocker_confusion_count=6,
            good_blocker_confusion_count=1,
            material_difference=True,
            bad_personas_attempted=5,
            bad_personas_completed=5,
            good_personas_attempted=5,
            good_personas_completed=5,
            bad_category_counts={"blocker": 1, "confusion": 5},
            good_category_counts={"delight": 1},
            bad_distinct_anchor_count=5,
            good_distinct_anchor_count=1,
            provenance=[
                AgentProvenance(
                    agent="persona", provider="anthropic", model="claude-haiku-4-5"
                ),
                AgentProvenance(
                    agent="moderator", provider="anthropic", model="claude-haiku-4-5"
                ),
                AgentProvenance(
                    agent="analyst", provider="anthropic", model="claude-sonnet-5"
                ),
            ],
        ),
        acquiescence_bias=AcquiescenceSection(
            status=MeasurementStatus.NOT_MEASURED_OFFLINE, reason="r", provenance=[]
        ),
        position_bias=PositionBiasSection(
            status=MeasurementStatus.NOT_MEASURED_OFFLINE, reason="r", provenance=[]
        ),
        known_answer_calibration=KnownAnswerCalibrationSection(
            status=MeasurementStatus.MEASURED,
            total_defects=3,
            detected_count=2,
            detection_rate=2 / 3,
            per_defect=[],
            personas_attempted=5,
            personas_completed=5,
            provenance=[
                AgentProvenance(
                    agent="analyst", provider="anthropic", model="claude-sonnet-5"
                ),
            ],
        ),
        clustering_margin=ClusteringMarginMeasurement(
            near_duplicate_max_internal_distance=0.4,
            distinct_pair_min_distance=0.6,
            margin=0.2,
            distance_threshold=0.6,
        ),
        zero_vector_conflation=ZeroVectorConflationMeasurement(
            zero_vector_singleton_count=1,
            genuine_frequency_one_singleton_count=1,
            total_singleton_clusters=2,
        ),
        threshold_scaling=ThresholdScalingMeasurement(
            distance_threshold=0.6, points=[]
        ),
    )

    text = render_validity_markdown(report)

    # Both configurations appear, distinctly, not merged into one line.
    assert "`persona`: fake/fake-1" in text
    assert "`analyst`: fake/fake-1" in text
    assert "`persona`: anthropic/claude-haiku-4-5" in text
    assert "`analyst`: anthropic/claude-sonnet-5" in text
    # The bare top-of-report "Provider: X / model: Y" line this replaced is gone.
    assert "Provider: `anthropic` / model: `claude-sonnet-5`" not in text
