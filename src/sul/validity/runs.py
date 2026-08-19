"""One shared "materialise + run a study against an artefact, return its
Finding rows" helper, used by every M6 check that runs the panel through
`run_study` (§M6.1's repeats, §M6.2's two artefacts). Factored out rather
than duplicated per check because a single `run_validity_harness` call
exercises several checks against the *same* artefact file
(`bad_onboarding.html` is used by both §M6.1 and §M6.2) in the same database
-- two independent `get_or_create_artefact`/`materialize_repeat_study` call
sites would still be correct individually, but one shared function is what
actually keeps them from drifting against each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul.analysis.clustering import FindingRow
from sul.db import session_scope
from sul.enums import ArtefactKind, RunStatus
from sul.models import Artefact, Panel, Persona, Run
from sul.models._util import utcnow
from sul.providers.base import LLMProvider
from sul.runner.orchestrator import run_study
from sul.validity.data import load_finding_rows
from sul.validity.materialize import get_or_create_artefact, materialize_repeat_study

DEFAULT_RESEARCH_GOAL = (
    "Determine whether new users can sign up without getting stuck on "
    "unclear required fields or mismatched pricing."
)
DEFAULT_SCENARIO_TASK = (
    "You've just landed on this page for the first time, looking to try the "
    "product out. Go ahead and sign up for the free trial."
)
DEFAULT_QUESTIONS = ["Was the pricing clear?", "Was anything confusing?"]


@dataclass(frozen=True)
class ArtefactStudyRun:
    """`run_artefact_study`'s result: the `Finding` rows *and* the
    materialised study's id, since callers that need real per-agent-role
    provenance (`sul.validity.data.load_provenance`) have to know which
    study's `ModelCall` rows to read back -- the rows alone don't carry
    that.
    """

    rows: list[FindingRow]
    study_id: int


async def run_artefact_study(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    artefact_path: str,
    panel_path: str,
    base_path: Path,
    study_name: str,
    research_goal: str = DEFAULT_RESEARCH_GOAL,
    scenario_task: str = DEFAULT_SCENARIO_TASK,
    questions: list[str] | None = None,
) -> ArtefactStudyRun:
    """Materialise `study_name` against `artefact_path` (reusing an existing
    `Artefact` row for that content if one already exists in this session),
    run it end to end via `provider`, and return its `Finding` rows and
    study id.
    """
    with session_factory() as session:
        artefact_id = get_or_create_artefact(
            session,
            name=Path(artefact_path).name,
            kind=ArtefactKind.HTML,
            path=base_path / artefact_path,
        )
        materialized = materialize_repeat_study(
            session,
            artefact_id=artefact_id,
            research_goal=research_goal,
            scenario_task=scenario_task,
            questions=list(questions)
            if questions is not None
            else list(DEFAULT_QUESTIONS),
            panel_config_path=panel_path,
            study_name=study_name,
            base_path=base_path,
        )
        session.commit()

    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name=provider_name,
        model=model,
    )

    with session_factory() as session:
        rows = load_finding_rows(session, study_id=materialized.study_id)
    return ArtefactStudyRun(rows=rows, study_id=materialized.study_id)


@dataclass(frozen=True)
class ProbeSubject:
    """One persona, ready for a single-shot probe call: no transcript, no
    turn loop -- §M6.3/§M6.4's probes bypass `run_study` entirely (see
    `sul.validity.probes`'s module docstring), but still need a `Run` row for
    their `ModelCall`s to attribute cost to, same as an Analyst call.
    """

    persona_id: int
    persona_name: str
    card_text: str
    run_id: int


@dataclass(frozen=True)
class ProbeMaterialization:
    study_id: int
    artefact_kind: ArtefactKind
    artefact_body: str
    panel_seed: int
    subjects: list[ProbeSubject]


async def materialize_probe_subjects(
    session_factory: sessionmaker[Session],
    *,
    artefact_path: str,
    panel_path: str,
    base_path: Path,
    study_name: str,
    research_goal: str = DEFAULT_RESEARCH_GOAL,
) -> ProbeMaterialization:
    """Materialise a study + panel against `artefact_path` (get-or-create the
    artefact, same as `run_artefact_study`) and one `Run` per persona -- no
    `run_study` turn loop, since a probe is one isolated call, not a
    multi-turn session.
    """
    with session_factory() as session:
        artefact_id = get_or_create_artefact(
            session,
            name=Path(artefact_path).name,
            kind=ArtefactKind.HTML,
            path=base_path / artefact_path,
        )
        materialized = materialize_repeat_study(
            session,
            artefact_id=artefact_id,
            research_goal=research_goal,
            scenario_task="Answer direct probe questions about the artefact.",
            questions=[],
            panel_config_path=panel_path,
            study_name=study_name,
            base_path=base_path,
        )
        session.commit()

    with session_factory() as session:
        artefact = session.get(Artefact, artefact_id)
        assert artefact is not None
        artefact_kind = artefact.kind
        artefact_body = artefact.body
        panel = session.get(Panel, materialized.panel_id)
        assert panel is not None
        panel_seed = panel.seed
        persona_rows = session.execute(
            select(Persona.id, Persona.name, Persona.card_text)
            .where(Persona.panel_id == materialized.panel_id)
            .order_by(Persona.id)
        ).all()

    subjects: list[ProbeSubject] = []
    for persona_id, persona_name, card_text in persona_rows:
        with session_scope(session_factory) as session:
            run = Run(
                study_id=materialized.study_id,
                persona_id=persona_id,
                scenario_id=materialized.scenario_id,
                status=RunStatus.COMPLETED,
                started_at=utcnow(),
                finished_at=utcnow(),
            )
            session.add(run)
            session.flush()
            run_id = run.id
        subjects.append(
            ProbeSubject(
                persona_id=persona_id,
                persona_name=persona_name,
                card_text=card_text,
                run_id=run_id,
            )
        )

    return ProbeMaterialization(
        study_id=materialized.study_id,
        artefact_kind=artefact_kind,
        artefact_body=artefact_body,
        panel_seed=panel_seed,
        subjects=subjects,
    )


__all__ = [
    "DEFAULT_QUESTIONS",
    "DEFAULT_RESEARCH_GOAL",
    "DEFAULT_SCENARIO_TASK",
    "ArtefactStudyRun",
    "ProbeMaterialization",
    "ProbeSubject",
    "materialize_probe_subjects",
    "run_artefact_study",
]
