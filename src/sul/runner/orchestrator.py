"""The M4 orchestrator: an async runner over the persona x scenario grid.

One `run_study` call drives every persona in a study's panel through one
scenario: Moderator opens with the scenario task -> Persona responds in
character -> Moderator asks up to `max_followups` adaptive follow-ups,
probing only on confusion/abandonment signals -> Analyst runs once the
transcript closes and emits `Finding[]` (PROJECT_SPEC.md §M4).

Concurrency is capped by an `asyncio.Semaphore`; because every engine in this
codebase uses SQLite's `StaticPool` (one underlying DBAPI connection for the
whole process -- see `tests/conftest.py::session_factory`), every actual
database write goes through `asyncio.to_thread` serialised by one
`asyncio.Lock` shared across the whole `run_study` call, regardless of the
concurrency cap. That cap therefore bounds *concurrent LLM calls* (the
rate-limiting concern the spec's "Concurrency cap (config)" bullet is
about), while database writes are always safely sequential.

Resumability (PROJECT_SPEC.md §M4 acceptance: "kill the process at 50% and
re-run -- it completes without duplicate `Run` rows") works off `Run`'s
`(study_id, persona_id, scenario_id)` uniqueness: a `COMPLETED` run is
skipped; anything else (missing, `PENDING`, `RUNNING`, or `FAILED` -- the
three states a killed process can leave behind) has its partial `Turn`/
`Finding` rows cleared and is (re)run from scratch, never duplicated.

A study-wide `BudgetGuard` failure (`BudgetExceeded`) is caught once, at the
per-run boundary -- never per-turn, never turned into a skipped turn or a
truncated-but-successful run. That run is marked `FAILED` with its
already-written turns left in place (PROJECT_SPEC.md §M4: "exits cleanly
with partial results saved"); because the guard is shared across every
`ModelClient` in the study, every other in-flight or not-yet-started call
starts failing the same way on its own next dispatch, so nothing keeps
spending. Any other exception (a genuinely unexpected failure -- the offline
analogue of the process actually being killed) is deliberately left
uncaught here and propagates out of `run_study`, leaving whatever was
already committed in place for the next `run_study` call to resume from.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.agents.analyst import run_analyst
from sul.agents.moderator import run_moderator_followup
from sul.agents.persona import run_persona_turn
from sul.db import session_scope
from sul.enums import AgentRole, ArtefactKind, RunStatus, TurnRole
from sul.models._util import utcnow
from sul.providers.base import LLMProvider
from sul.providers.budget import BudgetExceeded, BudgetGuard
from sul.providers.client import ModelClient, StructuredOutputError
from sul.runner.retry import call_with_backoff
from sul.runner.seeds import derive_seed
from sul.schemas.agents import AnalystFinding
from sul.schemas.isolation import AnalystContext, PersonaContext
from sul.schemas.run import TurnCreate


@dataclass(frozen=True)
class PersonaSlot:
    """One persona's plain-data identity for this study run -- read once, up
    front, as bare columns (never a live ORM `Persona`), so nothing about a
    persona's own relationships can accidentally travel into the turn loop.
    """

    persona_id: int
    persona_name: str
    card_text: str
    panel_seed: int


@dataclass(frozen=True)
class _StaticContext:
    research_goal: str
    scenario_task: str
    candidate_questions: list[str]
    artefact_kind: ArtefactKind
    artefact_body: str


@dataclass(frozen=True)
class _TurnRecord:
    ordinal: int
    role: TurnRole
    content: str
    turn_id: int


@dataclass(frozen=True)
class RunOutcome:
    run_id: int
    persona_id: int
    status: RunStatus
    error: str | None = None


@dataclass(frozen=True)
class StudyRunSummary:
    """What one `run_study` call did, broken out by outcome."""

    total_personas: int
    already_completed: int
    completed: list[RunOutcome] = field(default_factory=list)
    failed: list[RunOutcome] = field(default_factory=list)


async def _to_thread_locked[T](
    db_lock: asyncio.Lock | None, fn: Callable[..., T], *args: object, **kwargs: object
) -> T:
    """Run blocking `fn(*args, **kwargs)` in a worker thread, serialised
    through `db_lock` if one was given. See the module docstring for why.
    """
    if db_lock is None:
        return await asyncio.to_thread(fn, *args, **kwargs)
    async with db_lock:
        return await asyncio.to_thread(fn, *args, **kwargs)


def _load_static_context(
    session_factory: sessionmaker[Session], *, study_id: int, scenario_id: int
) -> _StaticContext:
    with session_factory() as session:
        study = session.get(models.Study, study_id)
        if study is None:
            raise ValueError(f"no Study with id={study_id}")
        scenario = session.get(models.Scenario, scenario_id)
        if scenario is None:
            raise ValueError(f"no Scenario with id={scenario_id}")
        artefact = session.get(models.Artefact, study.artefact_id)
        if artefact is None:
            raise ValueError(f"no Artefact with id={study.artefact_id}")
        return _StaticContext(
            research_goal=study.research_goal,
            scenario_task=scenario.task,
            candidate_questions=[str(q) for q in scenario.questions],
            artefact_kind=artefact.kind,
            artefact_body=artefact.body,
        )


def _load_persona_slots(
    session_factory: sessionmaker[Session], *, study_id: int
) -> list[PersonaSlot]:
    with session_factory() as session:
        rows = session.execute(
            select(
                models.Persona.id,
                models.Persona.name,
                models.Persona.card_text,
                models.Panel.seed,
            )
            .select_from(models.Persona)
            .join(models.Panel, models.Panel.id == models.Persona.panel_id)
            .where(models.Panel.study_id == study_id)
            .order_by(models.Persona.id)
        ).all()
    return [
        PersonaSlot(persona_id=pid, persona_name=name, card_text=card, panel_seed=seed)
        for pid, name, card, seed in rows
    ]


def _prepare_run(
    session_factory: sessionmaker[Session],
    *,
    study_id: int,
    scenario_id: int,
    persona_id: int,
) -> tuple[int, bool]:
    """Return `(run_id, already_completed)`. If a `Run` row already exists but
    isn't `COMPLETED` (missing entirely, `PENDING`, `RUNNING`, or `FAILED` --
    the states a killed process or a failed call can leave behind), any
    partial `Turn`/`Finding` rows are cleared and the row is reset to
    `PENDING` so the caller (re)runs it from scratch -- never a second `Run`
    row for the same `(study_id, persona_id, scenario_id)` triple.
    """
    with session_scope(session_factory) as session:
        existing = session.execute(
            select(models.Run).where(
                models.Run.study_id == study_id,
                models.Run.persona_id == persona_id,
                models.Run.scenario_id == scenario_id,
            )
        ).scalar_one_or_none()

        if existing is None:
            run = models.Run(
                study_id=study_id,
                persona_id=persona_id,
                scenario_id=scenario_id,
                status=RunStatus.PENDING,
            )
            session.add(run)
            session.flush()
            return run.id, False

        if existing.status == RunStatus.COMPLETED:
            return existing.id, True

        session.execute(delete(models.Turn).where(models.Turn.run_id == existing.id))
        session.execute(
            delete(models.Finding).where(models.Finding.run_id == existing.id)
        )
        existing.status = RunStatus.PENDING
        existing.started_at = None
        existing.finished_at = None
        existing.error = None
        session.flush()
        return existing.id, False


def _mark_run_running(session_factory: sessionmaker[Session], run_id: int) -> None:
    with session_scope(session_factory) as session:
        run = session.get(models.Run, run_id)
        assert run is not None
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()


def _mark_run_completed(session_factory: sessionmaker[Session], run_id: int) -> None:
    with session_scope(session_factory) as session:
        run = session.get(models.Run, run_id)
        assert run is not None
        run.status = RunStatus.COMPLETED
        run.finished_at = utcnow()


def _mark_run_failed(
    session_factory: sessionmaker[Session], run_id: int, error: str
) -> None:
    with session_scope(session_factory) as session:
        run = session.get(models.Run, run_id)
        assert run is not None
        run.status = RunStatus.FAILED
        run.finished_at = utcnow()
        run.error = error


def _write_turn(
    session_factory: sessionmaker[Session],
    *,
    run_id: int,
    role: TurnRole,
    ordinal: int,
    content: str,
) -> int:
    with session_scope(session_factory) as session:
        turn = TurnCreate(
            run_id=run_id, role=role, ordinal=ordinal, content=content
        ).to_orm()
        session.add(turn)
        session.flush()
        return turn.id


def _write_findings(
    session_factory: sessionmaker[Session],
    *,
    run_id: int,
    findings: list[AnalystFinding],
    ordinal_to_turn_id: dict[int, int],
) -> None:
    with session_scope(session_factory) as session:
        for f in findings:
            session.add(
                models.Finding(
                    run_id=run_id,
                    category=f.category,
                    severity=f.severity,
                    summary=f.summary,
                    evidence_turn_id=ordinal_to_turn_id[f.evidence_turn_ordinal],
                )
            )


async def _run_one_persona(
    *,
    slot: PersonaSlot,
    run_id: int,
    static_context: _StaticContext,
    session_factory: sessionmaker[Session],
    provider: LLMProvider,
    provider_name: str,
    model: str,
    model_by_agent: dict[AgentRole, str] | None,
    temperature: float,
    max_tokens: int,
    max_followups: int,
    budget: BudgetGuard | None,
    db_lock: asyncio.Lock,
    semaphore: asyncio.Semaphore,
) -> RunOutcome:
    persona_model = (model_by_agent or {}).get(AgentRole.PERSONA, model)
    moderator_model = (model_by_agent or {}).get(AgentRole.MODERATOR, model)
    analyst_model = (model_by_agent or {}).get(AgentRole.ANALYST, model)

    async with semaphore:
        persona_client = ModelClient(
            provider,
            provider_name,
            session_factory,
            agent=AgentRole.PERSONA,
            budget=budget,
            run_id=run_id,
            db_lock=db_lock,
        )
        moderator_client = ModelClient(
            provider,
            provider_name,
            session_factory,
            agent=AgentRole.MODERATOR,
            budget=budget,
            run_id=run_id,
            db_lock=db_lock,
        )
        analyst_client = ModelClient(
            provider,
            provider_name,
            session_factory,
            agent=AgentRole.ANALYST,
            budget=budget,
            run_id=run_id,
            db_lock=db_lock,
        )

        await _to_thread_locked(db_lock, _mark_run_running, session_factory, run_id)

        turns: list[_TurnRecord] = []
        try:
            ordinal = 0
            opening_id = await _to_thread_locked(
                db_lock,
                _write_turn,
                session_factory,
                run_id=run_id,
                role=TurnRole.MODERATOR,
                ordinal=ordinal,
                content=static_context.scenario_task,
            )
            turns.append(
                _TurnRecord(
                    ordinal,
                    TurnRole.MODERATOR,
                    static_context.scenario_task,
                    opening_id,
                )
            )
            ordinal += 1

            followups_used = 0
            while True:
                context = PersonaContext(
                    persona_card=slot.card_text,
                    artefact_kind=static_context.artefact_kind,
                    artefact_body=static_context.artefact_body,
                    moderator_turns=[
                        t.content for t in turns if t.role == TurnRole.MODERATOR
                    ],
                    transcript=[(t.role, t.content) for t in turns],
                )
                persona_seed = derive_seed(
                    panel_seed=slot.panel_seed,
                    persona_key=slot.persona_name,
                    agent=AgentRole.PERSONA,
                    turn_index=ordinal,
                )

                reply = await call_with_backoff(
                    functools.partial(
                        run_persona_turn,
                        client=persona_client,
                        context=context,
                        model=persona_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        seed=persona_seed,
                    )
                )

                persona_turn_id = await _to_thread_locked(
                    db_lock,
                    _write_turn,
                    session_factory,
                    run_id=run_id,
                    role=TurnRole.PERSONA,
                    ordinal=ordinal,
                    content=reply.utterance,
                )
                turns.append(
                    _TurnRecord(
                        ordinal, TurnRole.PERSONA, reply.utterance, persona_turn_id
                    )
                )
                ordinal += 1

                if reply.state not in ("confused", "gave_up"):
                    break
                if followups_used >= max_followups:
                    break

                followup_seed = derive_seed(
                    panel_seed=slot.panel_seed,
                    persona_key=slot.persona_name,
                    agent=AgentRole.MODERATOR,
                    turn_index=ordinal,
                )
                transcript_so_far = [(t.role, t.content) for t in turns]

                followup = await call_with_backoff(
                    functools.partial(
                        run_moderator_followup,
                        client=moderator_client,
                        research_goal=static_context.research_goal,
                        scenario_task=static_context.scenario_task,
                        candidate_questions=static_context.candidate_questions,
                        transcript=transcript_so_far,
                        model=moderator_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        seed=followup_seed,
                    )
                )

                followup_id = await _to_thread_locked(
                    db_lock,
                    _write_turn,
                    session_factory,
                    run_id=run_id,
                    role=TurnRole.MODERATOR,
                    ordinal=ordinal,
                    content=followup.question,
                )
                turns.append(
                    _TurnRecord(
                        ordinal, TurnRole.MODERATOR, followup.question, followup_id
                    )
                )
                ordinal += 1
                followups_used += 1

            analyst_context = AnalystContext(
                transcript=[(t.ordinal, t.role, t.content) for t in turns]
            )
            analyst_seed = derive_seed(
                panel_seed=slot.panel_seed,
                persona_key=slot.persona_name,
                agent=AgentRole.ANALYST,
                turn_index=ordinal,
            )

            findings = await call_with_backoff(
                functools.partial(
                    run_analyst,
                    client=analyst_client,
                    context=analyst_context,
                    model=analyst_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    seed=analyst_seed,
                )
            )

            if findings:
                ordinal_to_turn_id = {t.ordinal: t.turn_id for t in turns}
                await _to_thread_locked(
                    db_lock,
                    _write_findings,
                    session_factory,
                    run_id=run_id,
                    findings=findings,
                    ordinal_to_turn_id=ordinal_to_turn_id,
                )

            await _to_thread_locked(
                db_lock, _mark_run_completed, session_factory, run_id
            )
            return RunOutcome(
                run_id=run_id, persona_id=slot.persona_id, status=RunStatus.COMPLETED
            )
        except (BudgetExceeded, StructuredOutputError) as exc:
            # Caught once, at this per-run boundary -- never per-turn, and
            # never converted into a skipped turn or a truncated-but-
            # successful run. Everything already written for this run stays.
            await _to_thread_locked(
                db_lock, _mark_run_failed, session_factory, run_id, str(exc)
            )
            return RunOutcome(
                run_id=run_id,
                persona_id=slot.persona_id,
                status=RunStatus.FAILED,
                error=str(exc),
            )


async def run_study(
    session_factory: sessionmaker[Session],
    *,
    study_id: int,
    scenario_id: int,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    model_by_agent: dict[AgentRole, str] | None = None,
    temperature: float = 0.7,
    max_tokens: int = 400,
    max_followups: int = 3,
    concurrency: int = 1,
    budget: BudgetGuard | None = None,
) -> StudyRunSummary:
    """Run every persona in `study_id`'s panel(s) through `scenario_id` once.

    Idempotent at `Run` granularity: a persona whose `Run` is already
    `COMPLETED` is skipped; anything else is (re)run. Any exception other
    than `BudgetExceeded`/`StructuredOutputError` (both handled per-run, see
    the module docstring) propagates out of this call uncaught, leaving
    whatever was already committed in place for the next call to resume.

    `model` is the default model dispatched to every agent. `model_by_agent`
    optionally overrides it per `AgentRole` (`PERSONA`, `MODERATOR`,
    `ANALYST`) — an agent missing from the mapping falls back to `model`, so
    existing single-model callers that never pass `model_by_agent` are
    unaffected.
    """
    static_context = _load_static_context(
        session_factory, study_id=study_id, scenario_id=scenario_id
    )
    slots = _load_persona_slots(session_factory, study_id=study_id)

    pending: list[tuple[PersonaSlot, int]] = []
    already_completed = 0
    for slot in slots:
        run_id, was_completed = _prepare_run(
            session_factory,
            study_id=study_id,
            scenario_id=scenario_id,
            persona_id=slot.persona_id,
        )
        if was_completed:
            already_completed += 1
        else:
            pending.append((slot, run_id))

    db_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(max(1, concurrency))

    outcomes = await asyncio.gather(
        *(
            _run_one_persona(
                slot=slot,
                run_id=run_id,
                static_context=static_context,
                session_factory=session_factory,
                provider=provider,
                provider_name=provider_name,
                model=model,
                model_by_agent=model_by_agent,
                temperature=temperature,
                max_tokens=max_tokens,
                max_followups=max_followups,
                budget=budget,
                db_lock=db_lock,
                semaphore=semaphore,
            )
            for slot, run_id in pending
        )
    )

    completed = [o for o in outcomes if o.status == RunStatus.COMPLETED]
    failed = [o for o in outcomes if o.status == RunStatus.FAILED]
    return StudyRunSummary(
        total_personas=len(slots),
        already_completed=already_completed,
        completed=completed,
        failed=failed,
    )


__all__ = [
    "PersonaSlot",
    "RunOutcome",
    "StudyRunSummary",
    "run_study",
]
