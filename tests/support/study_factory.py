"""Shared helper for M4 tests: materialise a small, fast study (the 20-persona
fixture panel, `artefacts/bad_onboarding.html`) without going through a YAML
file on disk, so individual tests can override the research goal, scenario,
or panel path to inject sentinels.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.enums import ArtefactKind
from sul.runner.config import (
    ArtefactConfig,
    BudgetConfig,
    MaterializedStudy,
    RunnerOptions,
    ScenarioConfig,
    StudyRunConfig,
    materialize_study,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL_PATH = "tests/fixtures/panel_20.yaml"
DEFAULT_ARTEFACT_PATH = "artefacts/bad_onboarding.html"
DEFAULT_RESEARCH_GOAL = (
    "Determine whether new users can sign up without getting stuck on "
    "unclear required fields or mismatched pricing."
)
DEFAULT_SCENARIO_TASK = (
    "You've just landed on this page for the first time. Try to sign up "
    "for the free trial."
)
DEFAULT_QUESTIONS = ["Was the pricing clear?", "Was anything confusing?"]


def build_materialized_study(
    session_factory: sessionmaker[Session],
    *,
    research_goal: str = DEFAULT_RESEARCH_GOAL,
    scenario_task: str = DEFAULT_SCENARIO_TASK,
    questions: list[str] | None = None,
    panel_path: str = DEFAULT_PANEL_PATH,
    artefact_path: str = DEFAULT_ARTEFACT_PATH,
    max_cost_usd: float | None = None,
) -> MaterializedStudy:
    """Materialise a study and return its ids.

    Deliberately does *not* take `max_followups`/`concurrency`:
    `materialize_study` has nowhere to persist `RunnerOptions` (there is no
    column for it -- those are `run_study`'s own runtime parameters, not
    part of the persisted object graph), so a caller that wants a
    non-default value must pass it to `run_study(...)` directly. Accepting
    it here and silently discarding it would be exactly the kind of
    misleading, do-nothing config this project's own conventions reject.
    """
    config = StudyRunConfig(
        name="M4 test study",
        research_goal=research_goal,
        artefact=ArtefactConfig(
            name=Path(artefact_path).name, kind=ArtefactKind.HTML, path=artefact_path
        ),
        scenario=ScenarioConfig(
            task=scenario_task, questions=questions or DEFAULT_QUESTIONS
        ),
        panel_config_path=panel_path,
        budget=BudgetConfig(max_cost_usd=max_cost_usd),
        runner=RunnerOptions(),
    )
    with session_factory() as session:
        materialized = materialize_study(session, config, base_path=REPO_ROOT)
        session.commit()
    return materialized


__all__ = [
    "DEFAULT_PANEL_PATH",
    "DEFAULT_QUESTIONS",
    "DEFAULT_RESEARCH_GOAL",
    "DEFAULT_SCENARIO_TASK",
    "build_materialized_study",
]
