"""Shared fixture builder for M5 report tests (`test_report_build.py`,
`test_report_rendering.py`, `test_cli_report.py`): one hand-built object
graph with mixed run statuses, two segments, and findings deliberately built
to cluster into exactly one theme -- so those files share one ground truth
to assert counts against instead of drifting across near-duplicate fixtures.

Not `build_materialized_study` + `run_study` (M4's helper): that produces
FakeProvider's random-word findings, which are fine for plumbing/determinism
tests (`tests/support/run_report_script.py` uses it for exactly that) but
useless for asserting specific cluster membership, specific frequency counts,
or specific escaping-hazard content -- this module builds the object graph
by hand instead, the same way `tests/conftest.py`'s `StudyGraph` does for
isolation tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from sul import models
from sul.enums import ArtefactKind, FindingCategory, RunStatus, TurnRole

ESCAPING_HAZARD_QUOTE = (
    "The persona said: <script>alert('x')</script> & then | # maybe not\n"
    "```also this looks like a fence``` and a > blockquote marker"
)


@dataclass
class ReportFixture:
    study_id: int
    persona_ids: dict[str, int] = field(default_factory=dict)
    finding_ids: dict[str, int] = field(default_factory=dict)
    run_ids: dict[str, int] = field(default_factory=dict)


def build_report_fixture(
    session: Session, *, hazard_quote_on_second_ana_finding: bool = False
) -> ReportFixture:
    """Two segments, four personas, mixed run statuses:

    - Ana (students, COMPLETED): 2 findings, near-duplicate "submit button"
      text -- clusters with Ben's finding below.
    - Ben (students, COMPLETED): 1 finding, near-duplicate "submit button"
      text.
    - Cid (professionals, COMPLETED): 0 findings (a completed run with
      nothing to report is a legitimate, common outcome).
    - Dee (professionals, FAILED): a partial transcript (mirroring what M4's
      orchestrator actually persists on a mid-session failure) and no
      findings -- excluded from the denominator by default.
    - Eve (professionals, PENDING): never ran -- excluded from the
      denominator, and from `included`/`excluded` on a different axis than
      Dee (non-terminal, not terminal-but-unsuccessful).

    Denominator (default, `include_failed=False`): 3 (Ana, Ben, Cid).
    Segment denominators: students=2, professionals=1 (Cid only).
    The one cluster's frequency: 2 (Ana, Ben -- Cid contributed nothing).
    """
    artefact = models.Artefact(
        name="fixture.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
    )
    session.add(artefact)
    session.flush()

    study = models.Study(
        name="M5 report fixture study",
        research_goal="goal",
        artefact_id=artefact.id,
        config_hash="c1",
        git_sha="f" * 40,
    )
    session.add(study)
    session.flush()

    scenario = models.Scenario(study_id=study.id, task="task", questions=[])
    panel = models.Panel(study_id=study.id, seed=1, size=4, config_yaml="")
    session.add_all([scenario, panel])
    session.flush()

    def _persona(name: str, segment: str) -> models.Persona:
        persona = models.Persona(
            panel_id=panel.id,
            name=name,
            segment=segment,
            attributes={},
            card_text=f"card for {name}",
        )
        session.add(persona)
        session.flush()
        return persona

    ana = _persona("Ana", "students")
    ben = _persona("Ben", "students")
    cid = _persona("Cid", "professionals")
    dee = _persona("Dee", "professionals")
    eve = _persona("Eve", "professionals")

    fixture = ReportFixture(study_id=study.id)
    fixture.persona_ids = {
        "Ana": ana.id,
        "Ben": ben.id,
        "Cid": cid.id,
        "Dee": dee.id,
        "Eve": eve.id,
    }

    def _run(persona: models.Persona, status: RunStatus) -> models.Run:
        run = models.Run(
            study_id=study.id,
            persona_id=persona.id,
            scenario_id=scenario.id,
            status=status,
        )
        session.add(run)
        session.flush()
        return run

    def _turn(
        run: models.Run, role: TurnRole, ordinal: int, content: str
    ) -> models.Turn:
        turn = models.Turn(run_id=run.id, role=role, ordinal=ordinal, content=content)
        session.add(turn)
        session.flush()
        return turn

    def _finding(
        run: models.Run,
        evidence_turn: models.Turn,
        *,
        summary: str,
        severity: int,
        category: FindingCategory = FindingCategory.BLOCKER,
    ) -> models.Finding:
        finding = models.Finding(
            run_id=run.id,
            category=category,
            severity=severity,
            summary=summary,
            evidence_turn_id=evidence_turn.id,
        )
        session.add(finding)
        session.flush()
        return finding

    ana_run = _run(ana, RunStatus.COMPLETED)
    fixture.run_ids["Ana"] = ana_run.id
    _turn(ana_run, TurnRole.MODERATOR, 0, "Try signing up.")
    ana_turn_1 = _turn(
        ana_run, TurnRole.PERSONA, 1, "I could not find the submit button anywhere."
    )
    ana_turn_2_content = (
        ESCAPING_HAZARD_QUOTE
        if hazard_quote_on_second_ana_finding
        else "The submit button was nowhere to be found on the signup form."
    )
    ana_turn_2 = _turn(ana_run, TurnRole.PERSONA, 2, ana_turn_2_content)
    ana_finding_1 = _finding(
        ana_run,
        ana_turn_1,
        summary=(
            "The persona was unable to locate the submit button on the signup form."
        ),
        severity=4,
    )
    ana_finding_2 = _finding(
        ana_run,
        ana_turn_2,
        summary=(
            "The persona could not find the submit button while completing the "
            "signup form."
        ),
        severity=2,
    )
    fixture.finding_ids["Ana-1"] = ana_finding_1.id
    fixture.finding_ids["Ana-2"] = ana_finding_2.id

    ben_run = _run(ben, RunStatus.COMPLETED)
    fixture.run_ids["Ben"] = ben_run.id
    _turn(ben_run, TurnRole.MODERATOR, 0, "Try signing up.")
    ben_turn = _turn(
        ben_run,
        TurnRole.PERSONA,
        1,
        "I struggled to find the submit button after filling in the form.",
    )
    ben_finding = _finding(
        ben_run,
        ben_turn,
        summary=(
            "The persona struggled to find the submit button after filling in "
            "the signup form."
        ),
        severity=5,
    )
    fixture.finding_ids["Ben-1"] = ben_finding.id

    cid_run = _run(cid, RunStatus.COMPLETED)
    fixture.run_ids["Cid"] = cid_run.id
    _turn(cid_run, TurnRole.MODERATOR, 0, "Try signing up.")
    _turn(cid_run, TurnRole.PERSONA, 1, "That was easy, no problems.")

    dee_run = _run(dee, RunStatus.FAILED)
    dee_run.error = "budget exceeded"
    fixture.run_ids["Dee"] = dee_run.id
    _turn(dee_run, TurnRole.MODERATOR, 0, "Try signing up.")
    _turn(dee_run, TurnRole.PERSONA, 1, "This is taking a while...")

    eve_run = _run(eve, RunStatus.PENDING)
    fixture.run_ids["Eve"] = eve_run.id

    session.commit()
    return fixture


def build_single_finding_fixture(
    session: Session, *, quote: str, summary: str = "The persona reported a problem."
) -> int:
    """A minimal one-persona, one-finding study for isolated
    rendering/escaping tests that don't need the full multi-persona graph.
    Returns the study id.
    """
    artefact = models.Artefact(
        name="single.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
    )
    session.add(artefact)
    session.flush()
    study = models.Study(
        name="single-finding fixture study",
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
    session.flush()
    moderator_turn = models.Turn(
        run_id=run.id, role=TurnRole.MODERATOR, ordinal=0, content="Try signing up."
    )
    persona_turn = models.Turn(
        run_id=run.id, role=TurnRole.PERSONA, ordinal=1, content=quote
    )
    session.add_all([moderator_turn, persona_turn])
    session.flush()
    finding = models.Finding(
        run_id=run.id,
        category=FindingCategory.BLOCKER,
        severity=3,
        summary=summary,
        evidence_turn_id=persona_turn.id,
    )
    session.add(finding)
    session.commit()
    return study.id


__all__ = [
    "ESCAPING_HAZARD_QUOTE",
    "ReportFixture",
    "build_report_fixture",
    "build_single_finding_fixture",
]
