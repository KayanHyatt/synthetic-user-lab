"""The §M4 carry-forward's isolation tests: captured at the provider seam
(`RecordingProvider`), over the *whole* outbound payload -- system prompt,
every message turn, and schema field names/descriptions -- not a string the
test harness assembled itself.

Uses a `ScriptedProvider` rather than `FakeProvider` so the persona's `state`
(and therefore whether the moderator follow-up path fires at all) is under
the test's control, and the goal-sentinel is a distinctive multi-token,
invented-word sentence so a lightly reworded or reformatted goal would still
fail the check.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import ArtefactKind, TurnRole
from sul.providers.base import Completion, Message
from sul.providers.fake import FakeProvider
from sul.runner.orchestrator import run_study
from sul.schemas.agents import ModeratorFollowup, PersonaReply
from sul.schemas.isolation import AnalystContext, PersonaContext
from tests.support.recording_provider import RecordingProvider
from tests.support.scripted_provider import ScriptedProvider, text_completion
from tests.support.study_factory import build_materialized_study

GOAL_SENTINEL = (
    "ZZGOALZZ: determine whether ZZFIRSTBUYERZZ users abandon the "
    "ZZCHECKOUTZZ step because of the ZZSURCHARGEZZ fee"
)
_GOAL_WORDS = ["zzgoalzz", "zzfirstbuyerzz", "zzcheckoutzz", "zzsurchargezz"]


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def test_persona_context_forbids_extra_fields() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        PersonaContext(
            persona_card="card",
            artefact_kind=ArtefactKind.HTML,
            artefact_body="body",
            moderator_turns=[],
            transcript=[],
            topic="a smuggled goal",  # type: ignore[call-arg]
        )


def test_analyst_context_forbids_extra_fields() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        AnalystContext(transcript=[], research_goal="smuggled")  # type: ignore[call-arg]


def _always_confused_script(
    index: int,
    messages: list[Message],
    model: str,
    seed: int | None,
    response_schema: type[BaseModel] | None,
) -> Completion:
    if response_schema is PersonaReply:
        return text_completion(
            PersonaReply(utterance=f"turn {index}", state="confused").model_dump_json()
        )
    if response_schema is ModeratorFollowup:
        return text_completion(
            ModeratorFollowup(question=f"follow-up {index}").model_dump_json()
        )
    # The Analyst's schema is built fresh per run (a dynamic subclass), so it
    # can never be identified by `is`; detect it structurally instead.
    if response_schema is not None and "findings" in response_schema.model_fields:
        return text_completion(response_schema(findings=[]).model_dump_json())
    return text_completion("ok")


@pytest.mark.asyncio
async def test_goal_and_sibling_personas_never_leak_into_persona_payloads(
    session_factory: sessionmaker[Session],
) -> None:
    materialized = build_materialized_study(
        session_factory, research_goal=GOAL_SENTINEL
    )
    recorder = RecordingProvider(inner=ScriptedProvider(script=_always_confused_script))

    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=recorder,
        provider_name="fake",
        model="fake-1",
        max_followups=3,
    )

    persona_calls = recorder.persona_calls()
    moderator_calls = recorder.moderator_calls()

    # Positive control: this must not pass vacuously because nothing was
    # captured. 20 personas x 4 persona-directed calls each (forced
    # "confused" -> 3 follow-ups) = 80.
    assert len(persona_calls) >= 20
    assert len(moderator_calls) >= 1

    persona_payload = "\n".join(c.full_payload_text for c in persona_calls)
    normalized_persona_payload = _normalize(persona_payload)

    assert _normalize(GOAL_SENTINEL) not in normalized_persona_payload
    for word in _GOAL_WORDS:
        assert word not in normalized_persona_payload, (
            f"goal word {word!r} leaked into a persona-directed payload"
        )

    # Positive control on the goal check itself: the moderator *does* see it
    # (the documented laundering channel) -- if this failed, the absence
    # check above would be vacuous.
    moderator_payload = _normalize(
        "\n".join(c.full_payload_text for c in moderator_calls)
    )
    assert _normalize(GOAL_SENTINEL) in moderator_payload

    with session_factory() as session:
        personas = (
            session.execute(
                select(models.Persona)
                .where(models.Persona.panel_id == materialized.panel_id)
                .order_by(models.Persona.id)
            )
            .scalars()
            .all()
        )
    assert len(personas) == 20
    persona_a, persona_b = personas[0], personas[1]

    calls_with_a = [
        c for c in persona_calls if persona_a.card_text in c.full_payload_text
    ]
    calls_with_b = [
        c for c in persona_calls if persona_b.card_text in c.full_payload_text
    ]
    assert len(calls_with_a) == 4
    assert len(calls_with_b) == 4
    for call in calls_with_a:
        assert persona_b.card_text not in call.full_payload_text
        assert persona_b.name not in call.full_payload_text
    for call in calls_with_b:
        assert persona_a.card_text not in call.full_payload_text
        assert persona_a.name not in call.full_payload_text


def _echo_name_script(
    index: int,
    messages: list[Message],
    model: str,
    seed: int | None,
    response_schema: type[BaseModel] | None,
) -> Completion:
    if response_schema is PersonaReply:
        system_text = "\n".join(m.content for m in messages if m.role == "system")
        name = system_text.split("You are ", 1)[1].split(",", 1)[0]
        return text_completion(
            PersonaReply(
                utterance=f"ZZUTTERANCEZZ-{name}", state="proceeding"
            ).model_dump_json()
        )
    if response_schema is not None and "findings" in response_schema.model_fields:
        return text_completion(response_schema(findings=[]).model_dump_json())
    return text_completion("ok")


@pytest.mark.asyncio
async def test_persona_utterance_never_leaks_into_another_personas_payloads(
    session_factory: sessionmaker[Session],
) -> None:
    """Moderator/session state is scoped per persona session, not shared or
    accumulated across a loop over personas: run every persona in the panel,
    have each say something distinctive, and assert it appears nowhere but
    that persona's own transcript-derived (here: the Analyst's) payload.
    """
    materialized = build_materialized_study(session_factory)
    recorder = RecordingProvider(inner=ScriptedProvider(script=_echo_name_script))

    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=recorder,
        provider_name="fake",
        model="fake-1",
        max_followups=0,
    )

    with session_factory() as session:
        personas = (
            session.execute(
                select(models.Persona)
                .where(models.Persona.panel_id == materialized.panel_id)
                .order_by(models.Persona.id)
            )
            .scalars()
            .all()
        )
    assert len(personas) == 20

    for persona in personas:
        sentinel = f"ZZUTTERANCEZZ-{persona.name}"
        matches = [c for c in recorder.calls if sentinel in c.full_payload_text]
        assert len(matches) == 1, (
            f"{sentinel!r} appeared in {len(matches)} captured calls, expected "
            "exactly 1 (that persona's own Analyst call)"
        )
        assert matches[0].is_analyst_directed()


@pytest.mark.asyncio
async def test_fake_provider_produces_distinguishable_personas(
    session_factory: sessionmaker[Session],
) -> None:
    """The FakeProvider-degeneracy guard from the opposite direction: run the
    real `FakeProvider` (not scripted) and assert the panel doesn't collapse
    into one identical voice -- the failure mode if the derived per-turn
    seed were not actually threaded into the provider call.
    """
    materialized = build_materialized_study(session_factory)
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
        utterances = (
            session.execute(
                select(models.Turn.content)
                .join(models.Run, models.Run.id == models.Turn.run_id)
                .where(
                    models.Run.study_id == materialized.study_id,
                    models.Turn.role == TurnRole.PERSONA,
                )
            )
            .scalars()
            .all()
        )
    assert len(utterances) == 20
    assert len(set(utterances)) > 1, "every persona produced the same utterance"
