"""§M4 carry-forward: `ModelCall` accounting and the structured-output
failure path.

The invariant implemented here (stated, not assumed -- PROJECT_SPEC.md's
prompt warns against asserting `count(ModelCall) == n_turns` as a general
rule): every *dispatch* writes exactly one `ModelCall` row; one logical turn
is one dispatch, plus one more dispatch -- and therefore one more row -- iff
a repair turn fires. `count(Turn)` never changes because of a repair (a
repair produces the same logical turn, just parsed on the second attempt).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import RunStatus
from sul.providers.base import Completion, Message
from sul.providers.fake import FakeProvider
from sul.runner.orchestrator import run_study
from sul.schemas.agents import PersonaReply
from tests.support.scripted_provider import ScriptedProvider, text_completion
from tests.support.study_factory import build_materialized_study


def _counts_for_study(session: Session, study_id: int) -> tuple[int, int]:
    """Return `(total_turns, total_model_calls)` across every `Run` in `study_id`."""
    turns = session.execute(
        select(func.count(models.Turn.id))
        .select_from(models.Turn)
        .join(models.Run, models.Run.id == models.Turn.run_id)
        .where(models.Run.study_id == study_id)
    ).scalar_one()
    calls = session.execute(
        select(func.count(models.ModelCall.id))
        .select_from(models.ModelCall)
        .join(models.Run, models.Run.id == models.ModelCall.run_id)
        .where(models.Run.study_id == study_id)
    ).scalar_one()
    return turns, calls


@pytest.mark.asyncio
async def test_model_call_rows_no_repair_branch(
    session_factory: sessionmaker[Session],
) -> None:
    """One persona, no follow-ups, `FakeProvider` (always schema-valid, so no
    repair ever fires): 1 opening Turn (no ModelCall) + 1 persona Turn (1
    ModelCall) + 1 Analyst ModelCall (no Turn) = 2 Turns, 2 ModelCalls.
    """
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )
    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        max_followups=0,
    )
    with session_factory() as session:
        turns, calls = _counts_for_study(session, materialized.study_id)
        assert turns == 2
        assert calls == 2


_Script = Callable[
    [int, list[Message], str, int | None, type[BaseModel] | None], Completion
]


def _one_repair_script(state: dict[str, int]) -> _Script:
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
                return text_completion("not valid json {{{")
            return text_completion(
                PersonaReply(utterance="recovered", state="completed").model_dump_json()
            )
        if response_schema is not None and "findings" in response_schema.model_fields:
            return text_completion(response_schema(findings=[]).model_dump_json())
        return text_completion("ok")

    return script


@pytest.mark.asyncio
async def test_model_call_rows_one_repair_branch(
    session_factory: sessionmaker[Session],
) -> None:
    """The persona's first reply fails schema validation; the repair turn
    succeeds. Exactly one extra `ModelCall` row, and still exactly the same
    2 `Turn` rows -- the repair is the *same* logical turn, recorded twice
    only in the billing table.
    """
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )
    provider = ScriptedProvider(script=_one_repair_script({}))
    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name="fake",
        model="fake-1",
        max_followups=0,
    )
    assert len(summary.completed) == 1
    with session_factory() as session:
        turns, calls = _counts_for_study(session, materialized.study_id)
        assert turns == 2
        assert calls == 3  # persona attempt + persona repair + analyst

        persona_turn = session.execute(
            select(models.Turn).where(models.Turn.ordinal == 1)
        ).scalar_one()
        assert persona_turn.content == "recovered"


def _always_malformed_persona_script(
    index: int,
    messages: list[Message],
    model: str,
    seed: int | None,
    response_schema: type[BaseModel] | None,
) -> Completion:
    if response_schema is PersonaReply:
        return text_completion("not valid json, ever {{{")
    if response_schema is not None and "findings" in response_schema.model_fields:
        return text_completion(response_schema(findings=[]).model_dump_json())
    return text_completion("ok")


@pytest.mark.asyncio
async def test_terminal_parse_failure_fails_the_run_loudly_and_others_are_unaffected(
    session_factory: sessionmaker[Session],
) -> None:
    """Persona output is parsed through M2's structured-output path with no
    second repair layer, no fallback default, no post-hoc string cleaning.
    A terminal parse failure marks *that* Run `FAILED` with the error
    recorded, writes no Turn for the failed attempt, and does not touch any
    other persona's Run.
    """
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_2.yaml"
    )
    provider = ScriptedProvider(script=_always_malformed_persona_script)
    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name="fake",
        model="fake-1",
        max_followups=0,
    )
    assert len(summary.completed) == 0
    assert len(summary.failed) == 2

    with session_factory() as session:
        runs = (
            session.execute(
                select(models.Run).where(models.Run.study_id == materialized.study_id)
            )
            .scalars()
            .all()
        )
        assert len(runs) == 2
        for run in runs:
            assert run.status == RunStatus.FAILED
            assert run.error is not None and "PersonaReply" in run.error
            turn_count = session.execute(
                select(func.count(models.Turn.id)).where(models.Turn.run_id == run.id)
            ).scalar_one()
            # Only the opening turn (no LLM call) -- the persona turn that
            # failed to parse never got written.
            assert turn_count == 1
