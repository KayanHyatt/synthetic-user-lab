"""Materialisation helpers M4's `sul.runner.config.materialize_study` doesn't
cover: M6 is the first caller that runs *multiple* studies against the *same*
artefact (reproducibility repeats; two matched framing/position probes over
one panel). `materialize_study` always inserts a fresh `Artefact` row, and
`Artefact.content_hash` is unique -- calling it twice for the same artefact
body raises `IntegrityError`. This module reuses everything `materialize_study`
reuses (`sample_panel`, `persist_panel`, `StudyCreate`, `ScenarioCreate`) and
only replaces the one part that doesn't generalise: artefact creation becomes
get-or-create, keyed on the same `content_hash` the uniqueness constraint
already enforces.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sul.enums import ArtefactKind
from sul.gitinfo import current_git_sha
from sul.hashing import config_hash, content_hash
from sul.models import Artefact
from sul.personas.archetypes import load_panel_config
from sul.personas.persistence import persist_panel
from sul.personas.sampler import sample_panel
from sul.runner.config import MaterializedStudy
from sul.schemas.study import ScenarioCreate, StudyCreate


def get_or_create_artefact(
    session: Session, *, name: str, kind: ArtefactKind, path: Path
) -> int:
    """Return an existing `Artefact.id` for `path`'s content, or insert one.

    Keyed on `content_hash(body)` -- the same value `Artefact.content_hash`'s
    unique constraint already enforces -- so this never races the constraint
    it's working around.
    """
    body = path.read_text(encoding="utf-8")
    digest = content_hash(body)
    existing = session.execute(
        select(Artefact.id).where(Artefact.content_hash == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    artefact = Artefact(name=name, kind=kind, content_hash=digest, body=body)
    session.add(artefact)
    session.flush()
    return artefact.id


def materialize_repeat_study(
    session: Session,
    *,
    artefact_id: int,
    research_goal: str,
    scenario_task: str,
    questions: list[str],
    panel_config_path: str,
    study_name: str,
    base_path: Path,
) -> MaterializedStudy:
    """Persist a `Study` + `Panel`/`Persona`s + `Scenario` against an
    *already-materialised* artefact -- everything `materialize_study` does
    except inserting the `Artefact` row, so N calls with the same
    `artefact_id` are exactly N independent studies over one artefact, not N
    attempts to insert N duplicate artefacts.
    """
    panel_config = load_panel_config(base_path / panel_config_path)
    sampled = sample_panel(panel_config)

    study_config_hash = config_hash(
        {
            "research_goal": research_goal,
            "artefact_id": artefact_id,
            "scenario_task": scenario_task,
            "scenario_questions": list(questions),
            "panel_seed": panel_config.seed,
            "panel_size": panel_config.size,
        }
    )

    study = StudyCreate(
        name=study_name,
        research_goal=research_goal,
        artefact_id=artefact_id,
        config_hash=study_config_hash,
        git_sha=current_git_sha(),
    ).to_orm()
    session.add(study)
    session.flush()

    panel = persist_panel(
        session, study_id=study.id, config=panel_config, sampled=sampled
    )

    scenario = ScenarioCreate(
        study_id=study.id, task=scenario_task, questions=list(questions)
    ).to_orm()
    session.add(scenario)
    session.flush()

    return MaterializedStudy(
        study_id=study.id,
        scenario_id=scenario.id,
        artefact_id=artefact_id,
        panel_id=panel.id,
        persona_count=len(sampled.personas),
    )


__all__ = ["get_or_create_artefact", "materialize_repeat_study"]
