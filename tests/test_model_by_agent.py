"""`run_study(..., model_by_agent=...)`: an optional per-`AgentRole` model
override threaded through the turn loop's three dispatch sites (persona
turn, moderator follow-up, analyst). Existing single-model callers that
never pass `model_by_agent` must be unaffected -- that's `test_model_by_agent
_absent_falls_back_to_model` below.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import AgentRole
from sul.providers.base import Completion, Message
from sul.runner.orchestrator import run_study
from sul.schemas.agents import ModeratorFollowup, PersonaReply, PersonaState
from tests.support.scripted_provider import ScriptedProvider, text_completion
from tests.support.study_factory import build_materialized_study

_Script = Callable[
    [int, list[Message], str, int | None, type[BaseModel] | None], Completion
]


def _one_followup_script(state: dict[str, int]) -> _Script:
    """First persona reply signals confusion (triggers one moderator
    follow-up); second persona reply completes. Analyst returns no findings.
    """

    def script(
        index: int,
        messages: list[Message],
        model: str,
        seed: int | None,
        response_schema: type[BaseModel] | None,
    ) -> Completion:
        if response_schema is PersonaReply:
            state["persona_calls"] = state.get("persona_calls", 0) + 1
            persona_state: PersonaState = (
                "confused" if state["persona_calls"] == 1 else "completed"
            )
            return text_completion(
                PersonaReply(utterance="hm", state=persona_state).model_dump_json(),
                model=model,
            )
        if response_schema is ModeratorFollowup:
            return text_completion(
                ModeratorFollowup(question="what's unclear?").model_dump_json(),
                model=model,
            )
        if response_schema is not None and "findings" in response_schema.model_fields:
            return text_completion(
                response_schema(findings=[]).model_dump_json(), model=model
            )
        return text_completion("ok", model=model)

    return script


def _model_by_agent_for_study(
    session: Session, study_id: int
) -> dict[AgentRole, set[str]]:
    rows = session.execute(
        select(models.ModelCall.agent, models.ModelCall.model)
        .join(models.Run, models.Run.id == models.ModelCall.run_id)
        .where(models.Run.study_id == study_id)
    ).all()
    out: dict[AgentRole, set[str]] = {}
    for agent, model in rows:
        out.setdefault(agent, set()).add(model)
    return out


@pytest.mark.asyncio
async def test_model_by_agent_routes_each_agent_to_its_own_model(
    session_factory: sessionmaker[Session],
) -> None:
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )
    provider = ScriptedProvider(script=_one_followup_script({}))
    overrides = {
        AgentRole.PERSONA: "persona-model",
        AgentRole.MODERATOR: "moderator-model",
        AgentRole.ANALYST: "analyst-model",
    }
    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name="fake",
        model="fallback-model",
        model_by_agent=overrides,
        max_followups=1,
    )
    assert len(summary.completed) == 1

    with session_factory() as session:
        by_agent = _model_by_agent_for_study(session, materialized.study_id)

    assert by_agent[AgentRole.PERSONA] == {"persona-model"}
    assert by_agent[AgentRole.MODERATOR] == {"moderator-model"}
    assert by_agent[AgentRole.ANALYST] == {"analyst-model"}


@pytest.mark.asyncio
async def test_model_by_agent_absent_falls_back_to_model(
    session_factory: sessionmaker[Session],
) -> None:
    """No `model_by_agent` (the pre-existing call shape): every agent
    dispatches on the single `model` argument, unchanged from before this
    parameter existed.
    """
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )
    provider = ScriptedProvider(script=_one_followup_script({}))
    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name="fake",
        model="fallback-model",
        max_followups=1,
    )
    assert len(summary.completed) == 1

    with session_factory() as session:
        by_agent = _model_by_agent_for_study(session, materialized.study_id)

    assert by_agent[AgentRole.PERSONA] == {"fallback-model"}
    assert by_agent[AgentRole.MODERATOR] == {"fallback-model"}
    assert by_agent[AgentRole.ANALYST] == {"fallback-model"}


@pytest.mark.asyncio
async def test_model_by_agent_partial_override_falls_back_for_missing_agents(
    session_factory: sessionmaker[Session],
) -> None:
    """A `model_by_agent` mapping that only names some agents: named agents
    use their override, everything else falls back to `model`.
    """
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )
    provider = ScriptedProvider(script=_one_followup_script({}))
    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name="fake",
        model="fallback-model",
        model_by_agent={AgentRole.ANALYST: "analyst-model"},
        max_followups=1,
    )
    assert len(summary.completed) == 1

    with session_factory() as session:
        by_agent = _model_by_agent_for_study(session, materialized.study_id)

    assert by_agent[AgentRole.PERSONA] == {"fallback-model"}
    assert by_agent[AgentRole.MODERATOR] == {"fallback-model"}
    assert by_agent[AgentRole.ANALYST] == {"analyst-model"}
