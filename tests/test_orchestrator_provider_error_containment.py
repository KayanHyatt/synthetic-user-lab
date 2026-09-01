"""PROJECT_SPEC.md §M6 Deviation 11-13 / §M7 carry-forward, fixed here:
`sul.runner.orchestrator._run_one_persona`'s per-run containment used to
catch only `(BudgetExceeded, StructuredOutputError)`, never `ProviderError`
generally. A persona run that failed on `RateLimited` exhausted, `Refused`,
`BadRequest`, `Overloaded`, or a raw connection error was left stuck: never
marked `FAILED`, no `error` recorded, and the exception propagated all the
way out of `run_study` uncaught.

`Overloaded` is used here rather than `RateLimited`: `sul.runner.retry
.call_with_backoff` deliberately only retries `RateLimited` (see that
module's own docstring), so a single `Overloaded` raise reaches
`_run_one_persona`'s exception boundary directly, with no retry delay in
between.

`tests/fixtures/panel_2.yaml` (two personas) is used so the fix's other
half -- a sibling persona is unaffected by one persona's provider failure --
is exercised in the same test, not just the failing run in isolation.
`concurrency` defaults to 1, so with the shared `asyncio.Semaphore`
serialising the two personas' turn loops end to end, the very first
`PersonaReply`-schema dispatch belongs to whichever persona runs first;
scripting the failure on that first dispatch (rather than pinning it to a
specific persona id) keeps the test robust to which persona that turns out
to be.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import RunStatus
from sul.providers.base import Completion, Message, Overloaded
from sul.runner.orchestrator import run_study
from sul.schemas.agents import PersonaReply
from tests.support.scripted_provider import ScriptedProvider, text_completion
from tests.support.study_factory import build_materialized_study

_Script = Callable[
    [int, list[Message], str, int | None, type[BaseModel] | None], Completion
]


def _overloaded_on_first_persona_call(state: dict[str, int]) -> _Script:
    def script(
        index: int,
        messages: list[Message],
        model: str,
        seed: int | None,
        response_schema: type[BaseModel] | None,
    ) -> Completion:
        if response_schema is PersonaReply:
            state["persona_calls"] = state.get("persona_calls", 0) + 1
            if state["persona_calls"] == 1:
                raise Overloaded("simulated overload on the first persona dispatch")
            return text_completion(
                PersonaReply(utterance="ok", state="completed").model_dump_json()
            )
        if response_schema is not None and "findings" in response_schema.model_fields:
            return text_completion(response_schema(findings=[]).model_dump_json())
        return text_completion("ok")

    return script


@pytest.mark.asyncio
async def test_a_provider_error_other_than_budget_marks_the_run_failed(
    session_factory: sessionmaker[Session],
) -> None:
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_2.yaml"
    )
    provider = ScriptedProvider(script=_overloaded_on_first_persona_call({}))

    raised: Exception | None = None
    summary = None
    try:
        summary = await run_study(
            session_factory,
            study_id=materialized.study_id,
            scenario_id=materialized.scenario_id,
            provider=provider,
            provider_name="fake",
            model="fake-1",
            max_followups=0,
        )
    except Exception as exc:  # the exact bug: run_study should never propagate this
        raised = exc

    with session_factory() as session:
        runs = (
            session.execute(
                select(models.Run)
                .where(models.Run.study_id == materialized.study_id)
                .order_by(models.Run.persona_id)
            )
            .scalars()
            .all()
        )
    assert len(runs) == 2
    run_states = [(r.status, r.error) for r in runs]

    assert raised is None, (
        f"run_study propagated {raised!r} instead of catching it at "
        f"_run_one_persona's per-run boundary and marking that run FAILED; "
        f"Run rows were left at {run_states}"
    )

    failed_runs = [r for r in runs if r.status == RunStatus.FAILED]
    completed_runs = [r for r in runs if r.status == RunStatus.COMPLETED]
    assert len(failed_runs) == 1, f"expected exactly one FAILED run, got {run_states}"
    assert failed_runs[0].error, "the failed run's error must be recorded, not null"
    assert len(completed_runs) == 1, (
        f"the sibling persona must complete unaffected, got {run_states}"
    )

    assert summary is not None
    assert len(summary.failed) == 1
    assert summary.failed[0].run_id == failed_runs[0].id
    assert summary.failed[0].error
    assert len(summary.completed) == 1
    assert summary.completed[0].run_id == completed_runs[0].id
