"""The three `docs/limitations.md` measurements (PROJECT_SPEC.md §M6,
Correction 2). All three are pure, offline, LLM-free -- no FakeProvider, no
database -- so unlike §M6.2-.5 there's no `NOT_MEASURED_OFFLINE` gate to test
around; the assertions here are the measurement itself.
"""

from __future__ import annotations

from sul.validity.measurements import (
    measure_clustering_margin,
    measure_threshold_scaling,
    measure_zero_vector_conflation,
)


def test_clustering_margin_is_positive_and_matches_the_documented_direction() -> None:
    """`sul.analysis.clustering`'s module docstring documents near-duplicate
    internal distances topping out ~0.45 against a closest "must stay apart"
    pair at ~0.65 -- both sides of `distance_threshold=0.6`. This fixture is
    built the same way (not identical numbers, since it's a fresh fixture)
    and must land in the same regime: a positive margin, straddling 0.6.
    """
    measurement = measure_clustering_margin()
    assert measurement.margin > 0
    assert (
        measurement.near_duplicate_max_internal_distance
        < measurement.distance_threshold
    )
    assert (
        measurement.distinct_pair_min_distance
        > measurement.near_duplicate_max_internal_distance
    )


def test_zero_vector_conflation_finds_both_kinds_of_singleton() -> None:
    """Negative control: the fixture deliberately contains one zero-vector
    finding and one genuine one-off. If this measurement ever reported 0
    zero-vector singletons, the detector itself would be broken, not just
    reporting a clean corpus.
    """
    measurement = measure_zero_vector_conflation()
    assert measurement.zero_vector_singleton_count >= 1
    assert measurement.genuine_frequency_one_singleton_count >= 1
    assert measurement.total_singleton_clusters == (
        measurement.zero_vector_singleton_count
        + measurement.genuine_frequency_one_singleton_count
    )


def test_threshold_scaling_reports_one_point_per_requested_corpus_size() -> None:
    measurement = measure_threshold_scaling((5, 10))
    assert [p.finding_count for p in measurement.points] == [5, 10]
    for point in measurement.points:
        assert point.cluster_count >= 1
        assert point.mean_cluster_size > 0


def test_threshold_scaling_is_deterministic() -> None:
    first = measure_threshold_scaling((20,))
    second = measure_threshold_scaling((20,))
    assert first == second
