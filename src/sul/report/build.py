"""Assemble a `ReportModel` for one study (PROJECT_SPEC.md §M5). All database
access lives here; `sul.analysis.*` and `sul.report.markdown`/`html` never
query.

**Persona identity comes from the Finding's own `run_id`, not from
`evidence_turn_id -> Turn -> Run -> Persona`.** Those two paths agree today
only because M4 scopes the Analyst to one run at a time -- deriving persona
identity from the evidence turn instead would make "8/14 personas" quietly
mean "8 personas whose turns got cited" rather than "8 personas who
reported it", and nothing in the M4 suite would tell the two apart while the
scoping invariant holds. This module reads `Finding.run_id` directly for
persona/segment attribution, and separately asserts that the resolved
evidence turn's own `run_id` matches -- enforced, not assumed.

**Segments are reached by an explicit column join** (`Persona.segment` is a
plain column; `Panel.study_id`/`Persona.panel_id` are plain FKs), never by
walking `Persona.panel` or `Panel.study`, which are `lazy="raise"`
deliberately (`sul.models.panel`). If that ever fires here, the fix is this
query, not the relationship.

**`Finding.cluster_id` is never written.** See the deviation note in
PROJECT_SPEC.md's M5 section: clustering is computed fresh on every call,
so a completed study's stored rows are never rewritten by a reporting
command.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import sklearn
from sqlalchemy import select
from sqlalchemy.orm import Session

from sul.analysis.clustering import FindingRow, cluster_findings
from sul.analysis.config import ClusteringConfig
from sul.analysis.ranking import rank_clusters
from sul.enums import RunStatus
from sul.models import Finding, Panel, Persona, Run, Study, Turn
from sul.report.model import (
    ClusterReport,
    EvidenceItem,
    ExclusionCount,
    ReportModel,
    SegmentBreakdown,
)


class StudyNotFoundError(Exception):
    """No `Study` row with the given id."""


def build_report(
    session: Session,
    *,
    study_id: int,
    clustering_config: ClusteringConfig | None = None,
    include_failed: bool = False,
) -> ReportModel:
    config = clustering_config or ClusteringConfig()

    study = session.get(Study, study_id)
    if study is None:
        raise StudyNotFoundError(f"no study with id={study_id}")

    run_rows = session.execute(
        select(Run.id, Run.status, Run.persona_id, Persona.segment)
        .join(Persona, Persona.id == Run.persona_id)
        .join(Panel, Panel.id == Persona.panel_id)
        .where(Panel.study_id == study_id)
    ).all()

    terminal_ok = {RunStatus.COMPLETED}
    if include_failed:
        terminal_ok.add(RunStatus.FAILED)

    included = [r for r in run_rows if r.status in terminal_ok]
    excluded = [r for r in run_rows if r.status not in terminal_ok]

    total_personas = len({r.persona_id for r in included})

    segment_persona_ids: dict[str, set[int]] = defaultdict(set)
    for r in included:
        segment_persona_ids[r.segment].add(r.persona_id)
    segment_denominators = {seg: len(ids) for seg, ids in segment_persona_ids.items()}

    excluded_status_counts = Counter(r.status.value for r in excluded)
    excluded_runs = [
        ExclusionCount(status=status, count=count)
        for status, count in sorted(excluded_status_counts.items())
    ]

    included_run_ids = [r.id for r in included]

    if not included_run_ids:
        return ReportModel(
            study_id=study.id,
            study_name=study.name,
            total_personas=0,
            included_run_count=0,
            excluded_runs=excluded_runs,
            total_findings=0,
            clusters=[],
            clustering_distance_threshold=config.distance_threshold,
            clustering_metric=config.metric,
            clustering_linkage=config.linkage,
            sklearn_version=sklearn.__version__,
            include_failed=include_failed,
        )

    finding_query_rows = session.execute(
        select(
            Finding,
            Turn.content,
            Turn.ordinal,
            Turn.run_id,
            Run.persona_id,
            Persona.name,
            Persona.segment,
        )
        .join(Turn, Turn.id == Finding.evidence_turn_id)
        .join(Run, Run.id == Finding.run_id)
        .join(Persona, Persona.id == Run.persona_id)
        .where(Finding.run_id.in_(included_run_ids))
        .order_by(Finding.id)
    ).all()

    finding_rows: list[FindingRow] = []
    for (
        finding,
        evidence_content,
        evidence_ordinal,
        evidence_turn_run_id,
        persona_id,
        persona_name,
        segment,
    ) in finding_query_rows:
        if evidence_turn_run_id != finding.run_id:
            raise AssertionError(
                f"Finding {finding.id}'s evidence_turn_id={finding.evidence_turn_id} "
                f"belongs to run {evidence_turn_run_id}, not the finding's own run "
                f"{finding.run_id} -- an evidence turn must always come from the "
                "same run as the finding that cites it."
            )
        finding_rows.append(
            FindingRow(
                finding_id=finding.id,
                run_id=finding.run_id,
                persona_id=persona_id,
                persona_name=persona_name,
                segment=segment,
                category=finding.category,
                severity=finding.severity,
                summary=finding.summary,
                evidence_turn_id=finding.evidence_turn_id,
                evidence_content=evidence_content,
                evidence_turn_ordinal=evidence_ordinal,
            )
        )

    assignments = cluster_findings(finding_rows, config)
    rows_by_id = {r.finding_id: r for r in finding_rows}
    ranked = rank_clusters(
        rows_by_id,
        assignments,
        segment_denominators=segment_denominators,
        total_denominator=total_personas,
    )

    clusters = [
        ClusterReport(
            cluster_id=rc.cluster_id,
            title=rc.title,
            modal_category=rc.modal_category,
            category_disagreement=rc.category_disagreement,
            frequency=rc.frequency,
            denominator=rc.denominator,
            mean_severity=rc.mean_severity,
            segment_breakdown=[
                SegmentBreakdown(
                    segment=s.segment, frequency=s.frequency, denominator=s.denominator
                )
                for s in rc.segment_breakdown
            ],
            evidence=[
                EvidenceItem(
                    finding_id=row.finding_id,
                    run_id=row.run_id,
                    persona_name=row.persona_name,
                    segment=row.segment,
                    quote=row.evidence_content,
                    evidence_turn_ordinal=row.evidence_turn_ordinal,
                    summary=row.summary,
                )
                for row in sorted(
                    (rows_by_id[fid] for fid in rc.finding_ids),
                    key=lambda r: r.finding_id,
                )
            ],
        )
        for rc in ranked
    ]

    return ReportModel(
        study_id=study.id,
        study_name=study.name,
        total_personas=total_personas,
        included_run_count=len(included_run_ids),
        excluded_runs=excluded_runs,
        total_findings=len(finding_rows),
        clusters=clusters,
        clustering_distance_threshold=config.distance_threshold,
        clustering_metric=config.metric,
        clustering_linkage=config.linkage,
        sklearn_version=sklearn.__version__,
        include_failed=include_failed,
    )


__all__ = ["StudyNotFoundError", "build_report"]
