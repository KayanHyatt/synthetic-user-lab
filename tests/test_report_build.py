"""`sul.report.build.build_report` (PROJECT_SPEC.md §M5): terminal-run
filtering, segment access without tripping `Persona.panel`'s `lazy="raise"`,
zero-findings/unknown-study-id handling, the evidence-turn/finding-run
invariant, and that `Finding.cluster_id` is never written (the §8 deviation:
clustering is computed fresh on every call, never persisted).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.analysis.config import ClusteringConfig
from sul.enums import ArtefactKind, FindingCategory, RunStatus, TurnRole
from sul.report.build import StudyNotFoundError, build_report
from tests.support.report_factory import build_report_fixture


def test_terminal_only_filtering_excludes_failed_and_pending_by_default(
    session: Session,
) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)

    assert report.total_personas == 3  # Ana, Ben, Cid
    assert report.included_run_count == 3
    assert report.total_findings == 3

    excluded = {e.status: e.count for e in report.excluded_runs}
    assert excluded == {"failed": 1, "pending": 1}


def test_include_failed_flag_changes_denominator_and_exclusions(
    session: Session,
) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id, include_failed=True)

    assert report.total_personas == 4  # Ana, Ben, Cid, Dee
    assert report.included_run_count == 4
    excluded = {e.status: e.count for e in report.excluded_runs}
    assert excluded == {"pending": 1}
    assert report.include_failed is True


def test_segments_reached_without_tripping_lazy_raise(session: Session) -> None:
    """This test's mere success is the regression guard: `Persona.panel` and
    `Panel.study` are `lazy="raise"` (`sul.models.panel`); if `build_report`
    ever starts walking those relationships instead of joining on the plain
    FK columns, this raises `InvalidRequestError` instead of returning.
    """
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)

    assert len(report.clusters) == 1
    breakdown = {
        s.segment: (s.frequency, s.denominator)
        for s in report.clusters[0].segment_breakdown
    }
    assert breakdown == {"students": (2, 2), "professionals": (0, 1)}


def test_zero_findings_study_succeeds(session: Session) -> None:
    artefact = models.Artefact(
        name="a.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
    )
    session.add(artefact)
    session.flush()
    study = models.Study(
        name="empty study",
        research_goal="goal",
        artefact_id=artefact.id,
        config_hash="c1",
        git_sha="f" * 40,
    )
    session.add(study)
    session.flush()
    scenario = models.Scenario(study_id=study.id, task="task", questions=[])
    panel = models.Panel(study_id=study.id, seed=1, size=1, config_yaml="")
    session.add_all([scenario, panel])
    session.flush()
    persona = models.Persona(
        panel_id=panel.id, name="Solo", segment="seg", attributes={}, card_text="c"
    )
    session.add(persona)
    session.flush()
    run = models.Run(
        study_id=study.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status=RunStatus.COMPLETED,
    )
    session.add(run)
    session.commit()

    report = build_report(session, study_id=study.id)
    assert report.total_personas == 1
    assert report.total_findings == 0
    assert report.clusters == []


def test_unknown_study_id_raises_study_not_found(session: Session) -> None:
    with pytest.raises(StudyNotFoundError):
        build_report(session, study_id=999999)


def test_cluster_id_is_never_written_to_the_database(session: Session) -> None:
    fixture = build_report_fixture(session)
    build_report(session, study_id=fixture.study_id)

    findings = session.execute(select(models.Finding)).scalars().all()
    assert findings, "fixture must have produced at least one finding"
    assert all(f.cluster_id is None for f in findings)


def test_evidence_turn_must_belong_to_the_finding_s_own_run(
    session_factory: sessionmaker[Session],
) -> None:
    """Persona identity for frequency/segment counting comes from
    `Finding.run_id`, not from `evidence_turn_id -> Turn -> Run`. Those two
    paths agree by construction under M4, but this asserts it rather than
    assumes it -- corrupt a finding so its evidence turn belongs to a
    *different* run and confirm `build_report` refuses to proceed silently.
    """
    with session_factory() as session:
        fixture = build_report_fixture(session)

        # Point Ana's finding-1 evidence at Ben's run-opening turn instead of
        # her own -- a same-study, different-run turn.
        ana_finding = session.get(models.Finding, fixture.finding_ids["Ana-1"])
        assert ana_finding is not None
        ben_run_id = fixture.run_ids["Ben"]
        ben_moderator_turn = session.execute(
            select(models.Turn).where(
                models.Turn.run_id == ben_run_id, models.Turn.role == TurnRole.MODERATOR
            )
        ).scalar_one()
        ana_finding.evidence_turn_id = ben_moderator_turn.id
        session.commit()

        with pytest.raises(AssertionError):
            build_report(session, study_id=fixture.study_id)


def test_clustering_config_is_carried_into_the_report(session: Session) -> None:
    fixture = build_report_fixture(session)
    config = ClusteringConfig(distance_threshold=0.9)
    report = build_report(session, study_id=fixture.study_id, clustering_config=config)
    assert report.clustering_distance_threshold == 0.9
    assert report.clustering_metric == "cosine"
    assert report.clustering_linkage == "average"
    assert report.sklearn_version


def test_modal_category_reflects_fixture_findings(session: Session) -> None:
    fixture = build_report_fixture(session)
    report = build_report(session, study_id=fixture.study_id)
    assert report.clusters[0].modal_category == FindingCategory.BLOCKER
