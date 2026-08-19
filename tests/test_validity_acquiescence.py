"""PROJECT_SPEC.md §M6.3."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import ArtefactKind
from sul.providers.fake import FakeProvider
from sul.validity.acquiescence import agreement_rate, run_acquiescence_probe
from sul.validity.schemas import FramingProbeContext

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agreement_rate_pure_function() -> None:
    assert agreement_rate([]) == 0.0
    assert agreement_rate(["agree", "agree", "agree"]) == 1.0
    assert agreement_rate(["disagree", "disagree"]) == 0.0
    assert agreement_rate(["agree", "disagree", "unsure", "agree"]) == 0.5


def test_a_deliberately_biased_synthetic_panel_shows_a_large_gap() -> None:
    """Negative control: if every positively-framed reply is "agree" and every
    negatively-framed reply is "disagree", the gap must be reported at its
    maximum -- proving the statistic can detect acquiescence bias in
    principle, not just compute 0 by construction.
    """
    positive = agreement_rate(["agree"] * 5)
    negative = agreement_rate(["disagree"] * 5)
    assert abs(positive - negative) == 1.0


def test_an_unbiased_synthetic_panel_shows_no_gap() -> None:
    positive = agreement_rate(["agree", "disagree", "agree", "disagree"])
    negative = agreement_rate(["disagree", "agree", "disagree", "agree"])
    assert abs(positive - negative) == 0.0


def test_framing_probe_context_cannot_carry_a_research_goal() -> None:
    """Context isolation is enforced in code (PROJECT_SPEC.md §M4 carry-
    forward, extended to M6's probes): `extra="forbid"` makes a stray
    research-goal-shaped field a load-time error, not a silently-accepted
    extra.
    """
    with pytest.raises(ValidationError):
        FramingProbeContext(
            persona_card="card",
            artefact_kind=ArtefactKind.HTML,
            artefact_body="body",
            framed_question="q",
            research_goal="ZZGOALZZ",  # type: ignore[call-arg]
        )


@pytest.mark.asyncio
async def test_fakeprovider_runs_the_probe_end_to_end_offline(
    session_factory: sessionmaker[Session],
) -> None:
    result = await run_acquiescence_probe(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    assert 0.0 <= result.positive_agree_rate <= 1.0
    assert 0.0 <= result.negative_agree_rate <= 1.0
    assert 0.0 <= result.agreement_gap <= 1.0
