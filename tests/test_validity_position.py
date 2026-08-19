"""PROJECT_SPEC.md §M6.4."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import ArtefactKind
from sul.providers.fake import FakeProvider
from sul.validity.position import first_option_share, run_position_bias_probe
from sul.validity.schemas import ChoiceProbeContext

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
