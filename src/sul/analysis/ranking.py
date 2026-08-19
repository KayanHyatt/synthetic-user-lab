"""Rank clusters by `frequency x mean severity` and break each down by
segment (PROJECT_SPEC.md §M5). No LLM call, no database access -- pure
aggregation over `FindingRow`s already resolved by the caller.

**Frequency** counts distinct personas contributing at least one finding to
the cluster, never raw finding rows -- a persona whose Analyst pass produced
two findings in the same cluster still counts once. Counting raw rows would
let one voluble persona manufacture the appearance of consensus, which is
exactly the failure mode a synthetic panel is most likely to produce and
least likely to get caught on.

**Mean severity** is a mean of *per-persona* means, not a flat mean over
findings, for the same reason: a flat mean gives a persona with two findings
in a cluster twice the weight of a persona with one, which would make the
frequency half of the ranking formula (which deliberately normalises to one
unit per persona) disagree with the severity half about what a unit is.
Rendered in the report labelled "mean severity (model-assigned, 1-5;
averaged per persona)" -- it is the Analyst's assessment, not a measurement.

**Ties** (equal `frequency x mean severity`) are broken by the lowest
`finding_id` among a cluster's members -- never Python dict/set iteration
order, which is unspecified across processes for anything keyed on an
`int`-like hash in the way this codebase's other determinism tests already
guard against elsewhere (`sul.runner.seeds`, `sul.personas.sampler`).
"""

from __future__ import annotations

from collections import Counter, defaultdict

from pydantic import BaseModel, ConfigDict

from sul.analysis.clustering import ClusterAssignment, FindingRow
from sul.enums import FindingCategory


class SegmentCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment: str
    frequency: int
    denominator: int


class RankedCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: int
    title: str
    modal_category: FindingCategory
    category_disagreement: bool
    frequency: int
    denominator: int
    mean_severity: float
    rank_score: float
    segment_breakdown: list[SegmentCount]
    finding_ids: list[int]


def rank_clusters(
    rows_by_id: dict[int, FindingRow],
    assignments: list[ClusterAssignment],
    *,
    segment_denominators: dict[str, int],
    total_denominator: int,
) -> list[RankedCluster]:
    results: list[RankedCluster] = []

    for assignment in assignments:
        members = [rows_by_id[fid] for fid in assignment.finding_ids]

        per_persona_severities: dict[int, list[int]] = defaultdict(list)
        for member in members:
            per_persona_severities[member.persona_id].append(member.severity)
        per_persona_means = [
            sum(severities) / len(severities)
            for _persona_id, severities in sorted(per_persona_severities.items())
        ]
        frequency = len(per_persona_means)
        mean_severity = sum(per_persona_means) / len(per_persona_means)

        category_counts = Counter(member.category for member in members)
        max_count = max(category_counts.values())
        modal_category = min(
            (c for c, n in category_counts.items() if n == max_count),
            key=lambda c: c.value,
        )
        category_disagreement = len(category_counts) > 1

        segment_personas: dict[str, set[int]] = defaultdict(set)
        for member in members:
            segment_personas[member.segment].add(member.persona_id)
        # Every segment present in the study gets a row, including 0/N --
        # omitting a segment with zero contributing personas would read as
        # "not measured" rather than "measured, nobody reported it".
        segment_breakdown = [
            SegmentCount(
                segment=segment,
                frequency=len(segment_personas.get(segment, set())),
                denominator=denominator,
            )
            for segment, denominator in sorted(segment_denominators.items())
        ]

        results.append(
            RankedCluster(
                cluster_id=assignment.cluster_id,
                title=assignment.title,
                modal_category=modal_category,
                category_disagreement=category_disagreement,
                frequency=frequency,
                denominator=total_denominator,
                mean_severity=mean_severity,
                rank_score=frequency * mean_severity,
                segment_breakdown=segment_breakdown,
                finding_ids=list(assignment.finding_ids),
            )
        )

    results.sort(key=lambda r: (-r.rank_score, min(r.finding_ids)))
    return results


__all__ = ["RankedCluster", "SegmentCount", "rank_clusters"]
