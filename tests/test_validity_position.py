"""PROJECT_SPEC.md §M6.4."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import ArtefactKind
from sul.providers.base import Completion, Message
from sul.providers.fake import FakeProvider
from sul.validity.position import first_option_share, run_position_bias_probe
from sul.validity.schemas import ChoiceProbeContext
from tests.support.scripted_provider import ScriptedProvider, text_completion

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_first_option_share_pure_function() -> None:
    assert first_option_share([], "A") == 0.0
    assert first_option_share(["A", "A", "A"], "A") == 1.0
    assert first_option_share(["B", "B"], "A") == 0.0
    assert first_option_share(["A", "B"], "A") == 0.5


def test_a_deliberate_position_effect_is_detected() -> None:
    """Negative control: a synthetic panel that always picks whichever
    option is placed first, regardless of its label, must show maximal
    preference shift -- the option-A share flips from 1.0 (A first) to 0.0
    (A second) purely because of position.
    """
    share_when_a_first = first_option_share(["A", "A", "A"], "A")
    share_when_a_second = first_option_share(["B", "B", "B"], "A")
    assert abs(share_when_a_first - share_when_a_second) == 1.0


def test_no_position_effect_when_the_same_option_always_wins() -> None:
    share_when_a_first = first_option_share(["A", "A"], "A")
    share_when_a_second = first_option_share(["A", "A"], "A")
    assert abs(share_when_a_first - share_when_a_second) == 0.0


def test_choice_probe_context_cannot_carry_a_research_goal() -> None:
    with pytest.raises(ValidationError):
        ChoiceProbeContext(
            persona_card="card",
            artefact_kind=ArtefactKind.HTML,
            artefact_body="body",
            options=("A", "B"),
            research_goal="ZZGOALZZ",  # type: ignore[call-arg]
        )


def _first_option_choosing_script(
    index: int,
    messages: list[Message],
    model: str,
    seed: int | None,
    response_schema: type[BaseModel] | None,
) -> Completion:
    """A controlled responder that always picks whatever option is listed
    first -- content-blind, position-driven, exactly the failure mode §M6.4
    exists to catch. Reads the real rendered prompt (`render_choice_probe
    _prompt`'s "1. {option}" line) rather than assuming a fixed option
    identity, and replies through the real run-specific `Literal` schema
    `build_choice_probe_schema` built, the same as a real provider would.
    """
    prompt = messages[-1].content
    match = re.search(r"^1\. (.+)$", prompt, re.MULTILINE)
    assert match is not None, f"no numbered option found in prompt:\n{prompt}"
    first_option = match.group(1).strip()
    assert response_schema is not None
    reply = response_schema(choice=first_option)
    return text_completion(reply.model_dump_json(), model=model)


@pytest.mark.asyncio
async def test_a_content_blind_position_biased_provider_is_detected_through_pipeline(
    session_factory: sessionmaker[Session],
) -> None:
    """The real-harness-path version of the pure-function negative control
    above: `_first_option_choosing_script` never sees `first_option_share`
    or a synthetic list, only prompts built by `render_choice_probe_prompt`
    and dispatched by the real `ModelClient`, through the real per-call
    `Literal`-constrained schema. If the shuffling/attribution wiring in
    `run_position_bias_probe` were broken, this would not land on maximal
    shift.
    """
    result = await run_position_bias_probe(
        session_factory,
        provider=ScriptedProvider(script=_first_option_choosing_script),
        provider_name="fake",
        model="fake-1",
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    assert result.first_position_share_original_order == 1.0
    assert result.first_position_share_reversed_order == 0.0
    assert result.preference_shift == 1.0


@pytest.mark.asyncio
async def test_fakeprovider_runs_the_probe_end_to_end_offline(
    session_factory: sessionmaker[Session],
) -> None:
    result = await run_position_bias_probe(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    assert 0.0 <= result.first_position_share_original_order <= 1.0
    assert 0.0 <= result.first_position_share_reversed_order <= 1.0
    assert 0.0 <= result.preference_shift <= 1.0
