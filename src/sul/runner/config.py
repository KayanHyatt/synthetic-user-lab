"""Study run configuration: artefact + scenario + panel + budget
(PROJECT_SPEC.md §3), plus the runner options (concurrency, follow-up cap,
provider/model) that §M4 requires be configurable rather than hardcoded.

`configs/study.example.yaml` is a `StudyRunConfig` document. Neither this
schema nor the example file is named explicitly by any milestone's acceptance
criteria; M4 is its first consumer, since M4 is the first milestone that
needs "artefact + scenario + panel + budget" assembled into one runnable
study.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sul.enums import ArtefactKind
from sul.gitinfo import current_git_sha
from sul.hashing import config_hash, content_hash
from sul.models import Artefact
from sul.personas.archetypes import load_panel_config
from sul.personas.persistence import persist_panel
from sul.personas.sampler import sample_panel
from sul.schemas.study import ArtefactCreate, ScenarioCreate, StudyCreate


class ArtefactConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ArtefactKind
    path: str


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    questions: list[str] = Field(default_factory=list)


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float | None = None


class RunnerOptions(BaseModel):
    """Options the M4 orchestrator itself reads -- concurrency cap and
    follow-up cap are spec-required config (PROJECT_SPEC.md §M4: "Concurrency
    cap (config)"; "up to *k* follow-ups (config, default 3)").
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = "fake"
    model: str = "fake-1"
    temperature: float = 0.7
    max_tokens: int = 400
    concurrency: int = Field(default=1, ge=1)
    max_followups: int = Field(default=3, ge=0)


class StudyRunConfig(BaseModel):
    """A `configs/study.example.yaml`-shaped document: everything needed to
    materialise and then run one study end to end.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    research_goal: str
    artefact: ArtefactConfig
    scenario: ScenarioConfig
    panel_config_path: str
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    runner: RunnerOptions = Field(default_factory=RunnerOptions)


def load_study_config(path: str | Path) -> StudyRunConfig:
    """Load and parse a study config YAML file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("study config must be a YAML mapping")
    return StudyRunConfig.model_validate(raw)


class MaterializedStudy(BaseModel):
    """The ids `sul.runner.orchestrator.run_study` needs, once a
    `StudyRunConfig` has been persisted.
    """

    model_config = ConfigDict(extra="forbid")

    study_id: int
    scenario_id: int
    artefact_id: int
    panel_id: int
    persona_count: int


def materialize_study(
    session: Session, config: StudyRunConfig, *, base_path: Path | None = None
) -> MaterializedStudy:
    """Persist `config` as a `Study` + `Artefact` + `Panel`/`Persona`s +
    `Scenario`, and return the ids `run_study` needs.

    Not idempotent at the `Study` level -- calling this twice for the same
    `config` creates a second, independent study. `Artefact` rows *are*
    deduplicated by `content_hash` (PROJECT_SPEC.md §M7 deviation: this was
    the point of `Artefact.content_hash` being a content-address in the
    first place -- see `sul.hashing.content_hash`'s own docstring -- but
    materialisation never looked one up before inserting, so a second call
    with a byte-identical artefact body raised `IntegrityError` on
    `content_hash`'s UNIQUE constraint rather than reusing the existing row.
    Found running `sul demo` twice against a database that already had
    `artefacts/bad_onboarding.html` materialised under a different study).
    Resumability is a property of re-running `run_study` against one already-
    materialised `(study_id, scenario_id)`, not of this function.
    """
    root = base_path if base_path is not None else Path.cwd()
    artefact_body = (root / config.artefact.path).read_text(encoding="utf-8")
    artefact_content_hash = content_hash(artefact_body)

    artefact = session.execute(
        select(Artefact).where(Artefact.content_hash == artefact_content_hash)
    ).scalar_one_or_none()
    if artefact is None:
        artefact = ArtefactCreate(
            name=config.artefact.name, kind=config.artefact.kind, body=artefact_body
        ).to_orm()
        session.add(artefact)
        session.flush()

    panel_config = load_panel_config(root / config.panel_config_path)
    sampled = sample_panel(panel_config)

    study_config_hash = config_hash(
        {
            "research_goal": config.research_goal,
            "artefact_content_hash": artefact_content_hash,
            "scenario_task": config.scenario.task,
            "scenario_questions": list(config.scenario.questions),
            "panel_seed": panel_config.seed,
            "panel_size": panel_config.size,
        }
    )

    study = StudyCreate(
        name=config.name,
        research_goal=config.research_goal,
        artefact_id=artefact.id,
        config_hash=study_config_hash,
        git_sha=current_git_sha(),
    ).to_orm()
    session.add(study)
    session.flush()

    panel = persist_panel(
        session, study_id=study.id, config=panel_config, sampled=sampled
    )

    scenario = ScenarioCreate(
        study_id=study.id,
        task=config.scenario.task,
        questions=list(config.scenario.questions),
    ).to_orm()
    session.add(scenario)
    session.flush()

    return MaterializedStudy(
        study_id=study.id,
        scenario_id=scenario.id,
        artefact_id=artefact.id,
        panel_id=panel.id,
        persona_count=len(sampled.personas),
    )


__all__ = [
    "ArtefactConfig",
    "BudgetConfig",
    "MaterializedStudy",
    "RunnerOptions",
    "ScenarioConfig",
    "StudyRunConfig",
    "load_study_config",
    "materialize_study",
]
