"""`sul.analysis.ranking` (PROJECT_SPEC.md §M5): frequency counts distinct
personas (not raw finding rows), mean severity is a mean of per-persona
means (not a flat mean), and both halves of the ranking formula are broken
down by segment using the same persona-counted unit.
"""

from __future__ import annotations

from sul.analysis.clustering import ClusterAssignment, FindingRow
from sul.analysis.ranking import rank_clusters
from sul.enums import FindingCategory


def _row(
    finding_id: int,
    persona_id: int,
    segment: str,
    *,
    severity: int = 3,
    category: FindingCategory = FindingCategory.BLOCKER,
) -> FindingRow:
    return FindingRow(
        finding_id=finding_id,
        run_id=persona_id,
        persona_id=persona_id,
        persona_name=f"persona-{persona_id}",
        segment=segment,
        category=category,
        severity=severity,
        summary="s",
        evidence_turn_id=finding_id * 10,
        evidence_content="c",
        evidence_turn_ordinal=1,
    )


def test_frequency_counts_distinct_personas_not_raw_findings() -> None:
    """One voluble persona (id=1) contributes two findings to the same
    cluster; a second persona (id=2) contributes one. Frequency must be 2
    (distinct personas), not 3 (raw finding rows) -- the failure mode this
    guards against is one persona manufacturing the appearance of consensus.
    """
    rows = {
        1: _row(1, persona_id=1, segment="seg"),
        2: _row(2, persona_id=1, segment="seg"),
        3: _row(3, persona_id=2, segment="seg"),
    }
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1, 2, 3), title="t")
    ranked = rank_clusters(
        rows,
        [assignment],
        segment_denominators={"seg": 2},
        total_denominator=2,
    )
    assert ranked[0].frequency == 2


def test_mean_severity_is_mean_of_per_persona_means() -> None:
    """Persona 1 contributes severities [1, 5] (own mean 3.0); persona 2
    contributes [3] (own mean 3.0). A flat mean over all three findings would
    also read 3.0 here by coincidence, so persona 1's severities are chosen
    asymmetric enough that a flat-mean defect and a per-persona-mean
    implementation would disagree if persona counts differed -- see the
    second case below for that.
    """
    rows = {
        1: _row(1, persona_id=1, segment="seg", severity=1),
        2: _row(2, persona_id=1, segment="seg", severity=5),
        3: _row(3, persona_id=2, segment="seg", severity=3),
    }
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1, 2, 3), title="t")
    ranked = rank_clusters(
        rows, [assignment], segment_denominators={"seg": 2}, total_denominator=2
    )
    # per-persona means: persona 1 -> 3.0, persona 2 -> 3.0; mean of means = 3.0
    assert ranked[0].mean_severity == 3.0


def test_mean_severity_diverges_from_flat_mean_when_persona_counts_differ() -> None:
    """Persona 1 contributes three findings all severity 5; persona 2
    contributes one finding severity 1. Flat mean over findings = 4.0
    (5+5+5+1)/4. Mean of per-persona means = (5.0 + 1.0)/2 = 3.0. The two
    disagree, so this actually distinguishes the two aggregation methods
    rather than passing either way.
    """
    rows = {
        1: _row(1, persona_id=1, segment="seg", severity=5),
        2: _row(2, persona_id=1, segment="seg", severity=5),
        3: _row(3, persona_id=1, segment="seg", severity=5),
        4: _row(4, persona_id=2, segment="seg", severity=1),
    }
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1, 2, 3, 4), title="t")
    ranked = rank_clusters(
        rows, [assignment], segment_denominators={"seg": 2}, total_denominator=2
    )
    assert ranked[0].mean_severity == 3.0
    assert ranked[0].mean_severity != 4.0


def test_segment_breakdown_counts_distinct_personas_per_segment() -> None:
    rows = {
        1: _row(1, persona_id=1, segment="students"),
        2: _row(2, persona_id=2, segment="students"),
        3: _row(3, persona_id=3, segment="professionals"),
    }
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1, 2, 3), title="t")
    ranked = rank_clusters(
        rows,
        [assignment],
        segment_denominators={"students": 14, "professionals": 12},
        total_denominator=26,
    )
    breakdown = {
        s.segment: (s.frequency, s.denominator) for s in ranked[0].segment_breakdown
    }
    assert breakdown == {"students": (2, 14), "professionals": (1, 12)}


def test_segment_breakdown_includes_zero_frequency_segments() -> None:
    """A segment with zero personas contributing to this cluster still gets a
    row (0/N) -- omitting it would read as "not measured" rather than
    "measured, nobody in that segment reported it".
    """
    rows = {1: _row(1, persona_id=1, segment="students")}
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1,), title="t")
    ranked = rank_clusters(
        rows,
        [assignment],
        segment_denominators={"students": 5, "professionals": 3},
        total_denominator=8,
    )
    breakdown = {
        s.segment: (s.frequency, s.denominator) for s in ranked[0].segment_breakdown
    }
    assert breakdown == {"students": (1, 5), "professionals": (0, 3)}


def test_modal_category_and_disagreement_flag() -> None:
    rows = {
        1: _row(1, persona_id=1, segment="s", category=FindingCategory.PRICING),
        2: _row(2, persona_id=2, segment="s", category=FindingCategory.PRICING),
        3: _row(3, persona_id=3, segment="s", category=FindingCategory.TRUST),
    }
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1, 2, 3), title="t")
    ranked = rank_clusters(
        rows, [assignment], segment_denominators={"s": 3}, total_denominator=3
    )
    assert ranked[0].modal_category == FindingCategory.PRICING
    assert ranked[0].category_disagreement is True


def test_no_category_disagreement_when_unanimous() -> None:
    rows = {
        1: _row(1, persona_id=1, segment="s", category=FindingCategory.BLOCKER),
        2: _row(2, persona_id=2, segment="s", category=FindingCategory.BLOCKER),
    }
    assignment = ClusterAssignment(cluster_id=0, finding_ids=(1, 2), title="t")
    ranked = rank_clusters(
        rows, [assignment], segment_denominators={"s": 2}, total_denominator=2
    )
    assert ranked[0].category_disagreement is False


def test_ranking_orders_by_frequency_times_mean_severity_desc() -> None:
    rows = {
        1: _row(1, persona_id=1, segment="s", severity=5),
        2: _row(2, persona_id=2, segment="s", severity=5),
        3: _row(3, persona_id=3, segment="s", severity=1),
    }
    low_freq_high_sev = ClusterAssignment(cluster_id=0, finding_ids=(3,), title="low")
    high_freq_high_sev = ClusterAssignment(
        cluster_id=1, finding_ids=(1, 2), title="high"
    )
    ranked = rank_clusters(
        rows,
        [low_freq_high_sev, high_freq_high_sev],
        segment_denominators={"s": 3},
        total_denominator=3,
    )
    assert [r.cluster_id for r in ranked] == [1, 0]


def test_ranking_ties_break_on_lowest_member_finding_id_not_iteration_order() -> None:
    rows = {
        1: _row(1, persona_id=1, segment="s", severity=3),
        5: _row(5, persona_id=2, segment="s", severity=3),
    }
    # Same rank_score (1 persona * severity 3) for both -- tie-break must be
    # deterministic (lowest finding id first), regardless of the order the
    # assignments list is given in.
    a = ClusterAssignment(cluster_id=0, finding_ids=(5,), title="five")
    b = ClusterAssignment(cluster_id=1, finding_ids=(1,), title="one")
    ranked_forward = rank_clusters(
        rows, [a, b], segment_denominators={"s": 2}, total_denominator=2
    )
    ranked_backward = rank_clusters(
        rows, [b, a], segment_denominators={"s": 2}, total_denominator=2
    )
    assert [r.title for r in ranked_forward] == ["one", "five"]
    assert [r.title for r in ranked_backward] == ["one", "five"]
