"""All database access for the dashboard lives here -- routes and templates
never issue their own queries (the same discipline `sul.report.build` uses
for the M5 report: "All database access lives here").

**Segments are reached by an explicit column join**, mirroring
`sul.report.build.build_report` (`Persona.segment` is a plain column,
`Run.persona_id`/`Run.study_id` are plain FKs) -- never by walking
`Persona.panel`/`Panel.study`, which stay `lazy="raise"` (unchanged from
M1/M4). `Run.study_id` is used directly rather than routing through
`Panel.study_id` the way `build_report` does, since `Run` already carries
its own `study_id` column and no panel-level filtering is needed here.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sul.enums import RunStatus
from sul.models import Artefact, Finding, Persona, Run, Study, Turn
from sul.web.view_models import (
    FindingView,
    RunListItem,
    StudyListItem,
    TranscriptView,
    TurnView,
)


def list_studies(session: Session) -> list[StudyListItem]:
    """Every study, newest first, with a run-status breakdown per study."""
    study_rows = session.execute(
        select(Study.id, Study.name, Study.created_at, Artefact.name)
        .join(Artefact, Artefact.id == Study.artefact_id)
        .order_by(Study.id.desc())
    ).all()

    status_rows = session.execute(
        select(Run.study_id, Run.status, func.count(Run.id)).group_by(
            Run.study_id, Run.status
        )
    ).all()
    counts_by_study: dict[int, Counter[RunStatus]] = {}
    for study_id, status, count in status_rows:
        counts_by_study.setdefault(study_id, Counter())[status] = count

    items = []
    for study_id, name, created_at, artefact_name in study_rows:
        counts = counts_by_study.get(study_id, Counter())
        run_counts = {status: counts.get(status, 0) for status in RunStatus}
        items.append(
            StudyListItem(
                study_id=study_id,
                name=name,
                artefact_name=artefact_name,
                created_at=created_at,
                run_counts=run_counts,
                total_runs=sum(run_counts.values()),
            )
        )
    return items


def get_study_name(session: Session, study_id: int) -> str | None:
    return session.execute(
        select(Study.name).where(Study.id == study_id)
    ).scalar_one_or_none()


def list_runs(session: Session, study_id: int) -> list[RunListItem]:
    """Every run in `study_id`, with per-run turn/finding counts."""
    run_rows = session.execute(
        select(Run.id, Run.status, Persona.name, Persona.segment)
        .join(Persona, Persona.id == Run.persona_id)
        .where(Run.study_id == study_id)
        .order_by(Run.id)
    ).all()

    turn_counts: dict[int, int] = {
        run_id: count
        for run_id, count in session.execute(
            select(Turn.run_id, func.count(Turn.id))
            .join(Run, Run.id == Turn.run_id)
            .where(Run.study_id == study_id)
            .group_by(Turn.run_id)
        ).all()
    }
    finding_counts: dict[int, int] = {
        run_id: count
        for run_id, count in session.execute(
            select(Finding.run_id, func.count(Finding.id))
            .join(Run, Run.id == Finding.run_id)
            .where(Run.study_id == study_id)
            .group_by(Finding.run_id)
        ).all()
    }

    return [
        RunListItem(
            run_id=run_id,
            persona_name=persona_name,
            segment=segment,
            status=status,
            turn_count=turn_counts.get(run_id, 0),
            finding_count=finding_counts.get(run_id, 0),
        )
        for run_id, status, persona_name, segment in run_rows
    ]


def load_transcript(session: Session, run_id: int) -> TranscriptView | None:
    """One run's full transcript plus its findings, or `None` if `run_id`
    doesn't exist.
    """
    run_row = session.execute(
        select(
            Run.id,
            Run.study_id,
            Run.status,
            Study.name,
            Persona.name,
            Persona.segment,
        )
        .join(Study, Study.id == Run.study_id)
        .join(Persona, Persona.id == Run.persona_id)
        .where(Run.id == run_id)
    ).first()
    if run_row is None:
        return None
    _, study_id, status, study_name, persona_name, segment = run_row

    turn_rows = session.execute(
        select(Turn.id, Turn.role, Turn.ordinal, Turn.content)
        .where(Turn.run_id == run_id)
        .order_by(Turn.ordinal)
    ).all()
    finding_rows = session.execute(
        select(
            Finding.id,
            Finding.category,
            Finding.severity,
            Finding.summary,
            Finding.evidence_turn_id,
        )
        .where(Finding.run_id == run_id)
        .order_by(Finding.id)
    ).all()

    return TranscriptView(
        run_id=run_id,
        study_id=study_id,
        study_name=study_name,
        persona_name=persona_name,
        segment=segment,
        status=status,
        turns=[
            TurnView(turn_id=tid, role=role, ordinal=ordinal, content=content)
            for tid, role, ordinal, content in turn_rows
        ],
        findings=[
            FindingView(
                finding_id=fid,
                category=category,
                severity=severity,
                summary=summary,
                evidence_turn_id=evidence_turn_id,
            )
            for fid, category, severity, summary, evidence_turn_id in finding_rows
        ],
    )


__all__ = ["get_study_name", "list_runs", "list_studies", "load_transcript"]
