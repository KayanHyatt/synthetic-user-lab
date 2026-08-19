"""Budget is a pre-call gate, not a post-hoc tally (PROJECT_SPEC.md §M4,
enforced from M2 -- see the M2 implementation note in PROJECT_SPEC.md).

The decisive assertion is not just that `BudgetExceeded` is raised, but that
the underlying provider is never dispatched for the call that would exceed
the ceiling -- a test that only checks the raise would still pass if the
call had already been sent and billed before the exception was raised.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.models import ModelCall
from sul.providers.base import Completion, Message, Usage
from sul.providers.budget import BudgetExceeded, BudgetGuard
from sul.providers.client import ModelClient


class CountingProvider:
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
async def test_second_call_over_ceiling_is_blocked_and_never_dispatched(
    session_factory: sessionmaker[Session], study_and_run: tuple[int, int]
) -> None:
    study_id, run_id = study_and_run

    # `claude-opus-5` pricing (configs/pricing.yaml) so the pre-call
    # estimate is nonzero: a ceiling that fits a tiny first call but not a
    # second call with a much larger `max_tokens` (which the budget gate
    # must price at *max_tokens*, not at actual usage, since the call
    # hasn't happened yet).
    provider = CountingProvider()
    guard = BudgetGuard(session_factory, study_id=study_id, max_cost_usd=0.0011)
    client = ModelClient(
        provider,
        "anthropic",
        session_factory,
        agent=AgentRole.PERSONA,
        budget=guard,
        run_id=run_id,
    )

    text1 = await client.complete(
        messages=[Message(role="user", content="hi")],
        model="claude-opus-5",
        temperature=0.0,
        max_tokens=1,
        seed=1,
    )
    assert text1 == "ok"
    assert provider.dispatch_count == 1

    with pytest.raises(BudgetExceeded):
        await client.complete(
            messages=[Message(role="user", content="hi again, a much larger request")],
            model="claude-opus-5",
            temperature=0.0,
            max_tokens=100_000,
            seed=1,
        )

    # The decisive assertion: the transport was never invoked for the
    # blocked call. A test that only checks the raise would still pass if
    # the call had already been dispatched and billed.
    assert provider.dispatch_count == 1

    with session_factory() as session:
        rows = session.query(ModelCall).filter(ModelCall.run_id == run_id).all()
        # Exactly one row: the successful call. The blocked call never
        # dispatched, so it wrote nothing.
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_first_call_within_ceiling_is_not_blocked(
    session_factory: sessionmaker[Session], study_and_run: tuple[int, int]
) -> None:
    study_id, run_id = study_and_run
    provider = CountingProvider()
    guard = BudgetGuard(session_factory, study_id=study_id, max_cost_usd=1.0)
    client = ModelClient(
        provider,
        "anthropic",
        session_factory,
        agent=AgentRole.PERSONA,
        budget=guard,
        run_id=run_id,
    )

    result = await client.complete(
        messages=[Message(role="user", content="hi")],
        model="claude-opus-5",
        temperature=0.0,
        max_tokens=100,
        seed=1,
    )
    assert result == "ok"
    assert provider.dispatch_count == 1
