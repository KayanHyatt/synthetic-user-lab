"""Cost comes from a per-model price table, not a hardcoded call-site number
(PROJECT_SPEC.md §M2). An unpriced model must raise, never silently cost $0.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.models import ModelCall
from sul.pricing import (
    UnknownModelError,
    cost_for,
    estimate_cost,
    load_pricing,
    price_for,
)
from sul.providers.base import Completion, Message, Usage
from sul.providers.client import ModelClient


def test_pricing_table_loads_and_has_the_documented_anthropic_models() -> None:
    table = load_pricing()
    assert "claude-opus-5" in table["anthropic"]
    price = table["anthropic"]["claude-opus-5"]
    assert price.input > 0
    assert price.output > 0


def test_price_for_known_model() -> None:
    price = price_for("anthropic", "claude-opus-5")
    assert price.input == pytest.approx(0.000005)
    assert price.output == pytest.approx(0.000025)


def test_price_for_unknown_model_raises_rather_than_defaulting_to_zero() -> None:
    with pytest.raises(UnknownModelError):
        price_for("anthropic", "some-model-that-does-not-exist")

    with pytest.raises(UnknownModelError):
        price_for("openai", "gpt-5")  # openai section deliberately unpriced


def test_cost_for_known_tokens() -> None:
    price = price_for("anthropic", "claude-opus-5")
    cost = cost_for(price, tokens_in=1000, tokens_out=500)
    expected = price.input * 1000 + price.output * 500
    assert cost == pytest.approx(expected)


def test_estimate_cost_prices_the_output_side_at_max_tokens() -> None:
    """The budget gate estimates worst-case, not average-case, spend: the
    output side must be priced at `max_tokens`, not at some guessed average
    completion length.
    """
    price = price_for("anthropic", "claude-opus-5")
    estimate = estimate_cost(price, estimated_tokens_in=100, max_tokens=4000)
    expected = price.input * 100 + price.output * 4000
    assert estimate == pytest.approx(expected)


def test_fake_model_is_priced_at_zero() -> None:
    price = price_for("fake", "fake-1")
    assert price.input == 0.0
    assert price.output == 0.0


class _CountingProvider:
    """A provider stub that counts how many times it was actually dispatched."""

    def __init__(self) -> None:
        self.dispatch_count = 0

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: object | None = None,
    ) -> Completion:
        self.dispatch_count += 1
        return Completion(
            text="ok",
            usage=Usage(tokens_in=10, tokens_out=5),
            model=model,
            stop_reason="end_turn",
        )


@pytest.mark.asyncio
async def test_unpriced_model_raises_before_dispatch_via_model_client(
    session_factory: sessionmaker[Session], study_and_run: tuple[int, int]
) -> None:
    """`ModelClient._dispatch` prices the call before it checks the budget or
    touches the provider. An unpriced model must raise `UnknownModelError`
    right there -- not estimate at $0.00 and sail through the budget gate,
    and not raise only from adapter construction (which would let a
    `ModelClient` built around an already-constructed provider dispatch and
    bill an unpriced model with a $0.00 estimate).
    """
    _study_id, run_id = study_and_run
    provider = _CountingProvider()
    client = ModelClient(
        provider, "openai", session_factory, agent=AgentRole.PERSONA, run_id=run_id
    )

    with pytest.raises(UnknownModelError):
        await client.complete(
            messages=[Message(role="user", content="hi")],
            model="gpt-5",  # openai section of configs/pricing.yaml is empty
            temperature=0.0,
            max_tokens=100,
            seed=1,
        )

    assert provider.dispatch_count == 0

    with session_factory() as session:
        rows = session.query(ModelCall).filter(ModelCall.run_id == run_id).all()
        assert rows == []
