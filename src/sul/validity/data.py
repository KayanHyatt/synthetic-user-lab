"""Read-only `Finding` row loader for one study, joined the same way
`sul.report.build.build_report` joins them. M6 needs the rows themselves --
to count categories, re-cluster across independent repeat studies, match
against seeded defects -- not a rendered `ReportModel`, so this is a second,
smaller call site over the same tables rather than a second copy of
`build_report`'s clustering/ranking assembly. Read-only, same as M5's own DB
access; nothing here writes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sul.analysis.clustering import FindingRow
from sul.enums import RunStatus
from sul.models import Finding, ModelCall, Persona, Run, Turn
from sul.validity.model import AgentProvenance


def load_finding_rows(
    session: Session, *, study_id: int, include_failed: bool = False
) -> list[FindingRow]:
    terminal_ok = {RunStatus.COMPLETED}
    if include_failed:
        terminal_ok.add(RunStatus.FAILED)

    run_ids = (
        session.execute(
            select(Run.id).where(Run.study_id == study_id, Run.status.in_(terminal_ok))
        )
        .scalars()
        .all()
    )
    if not run_ids:
        return []

    query_rows = session.execute(
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
        .where(Finding.run_id.in_(run_ids))
        .order_by(Finding.id)
    ).all()

    result: list[FindingRow] = []
    for (
        finding,
        evidence_content,
        evidence_ordinal,
        evidence_turn_run_id,
        persona_id,
        persona_name,
        segment,
    ) in query_rows:
        if evidence_turn_run_id != finding.run_id:
            raise AssertionError(
                f"Finding {finding.id}'s evidence_turn_id={finding.evidence_turn_id} "
                f"belongs to run {evidence_turn_run_id}, not the finding's own run "
                f"{finding.run_id}."
            )
        result.append(
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
    return result


def load_provenance(session: Session, *, study_ids: list[int]) -> list[AgentProvenance]:
    """Distinct (provider, agent, model) triples actually dispatched for
    `study_ids`, read back from the `ModelCall` audit trail -- not threaded
    through as separate "what I intended to call" bookkeeping, which could
    silently drift from what a retry/backoff path or a future per-agent-role
    override actually sent. `ModelCall` is what this project already treats
    as the ground truth for cost and reproducibility (PROJECT_SPEC.md §M1);
    provenance is the same idea applied to "which model produced this
    number," and it's what let §M6's per-row provenance rendering
    (PROJECT_SPEC.md's M6 implementation note) describe reality instead of
    a plan. Ordered for byte-stable rendering, never dict/set iteration
    order.
    """
    if not study_ids:
        return []
    rows = session.execute(
        select(ModelCall.provider, ModelCall.agent, ModelCall.model)
        .join(Run, Run.id == ModelCall.run_id)
        .where(Run.study_id.in_(study_ids))
        .distinct()
        .order_by(ModelCall.agent, ModelCall.provider, ModelCall.model)
    ).all()
    return [
        AgentProvenance(agent=agent.value, provider=provider, model=model)
        for provider, agent, model in rows
    ]


def finding_content_key(row: FindingRow) -> tuple[str, str, str]:
    """A finding's identity by *content*, not by database row id.

    Two independent repeat studies (M6.1) each materialise a fresh `Study` /
    `Panel` / `Finding` graph, so `Finding.id` values never line up across
    repeats even when the underlying content is byte-identical (same seed ->
    same deterministic persona names/cards -> same `FakeProvider` hash ->
    same synthesized summary/category). Comparing `finding_id` sets across
    repeats would therefore always show 0 overlap regardless of whether the
    *content* reproduced -- this key is what actually lets two repeats' top-5
    clusters be compared.
    """
    return (row.persona_name, row.category.value, row.summary)


__all__ = ["finding_content_key", "load_finding_rows", "load_provenance"]
