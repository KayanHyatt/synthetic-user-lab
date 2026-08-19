"""`sul.runner.retry.call_with_backoff`: exponential backoff with jitter on
`RateLimited` (PROJECT_SPEC.md §M4), and only on `RateLimited`.
"""

from __future__ import annotations

import random

import pytest

from sul.providers.base import Overloaded, RateLimited
from sul.runner.retry import call_with_backoff


@pytest.mark.asyncio
async def test_succeeds_without_retry_when_first_attempt_works() -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await call_with_backoff(fn)
    assert result == "ok"
    assert calls == 1


@pytest.mark.asyncio
async def test_retries_rate_limited_and_eventually_succeeds() -> None:
    calls = 0
    delays: list[float] = []

    async def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RateLimited("slow down")
        return "ok"

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    result = await call_with_backoff(
        fn,
        rng=random.Random(0),
        sleep=fake_sleep,
        base_delay_seconds=0.1,
        jitter_seconds=0.1,
    )
    assert result == "ok"
    assert calls == 3
    assert len(delays) == 2
    # Exponential: second delay's base component is >= the first's.
    assert delays[1] >= delays[0] - 0.1  # jitter can narrow the gap slightly


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts() -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise RateLimited("still slow")

    async def fake_sleep(_seconds: float) -> None:
        return None

    with pytest.raises(RateLimited):
        await call_with_backoff(fn, max_attempts=3, sleep=fake_sleep)
    assert calls == 3


@pytest.mark.asyncio
async def test_overloaded_is_not_retried() -> None:
    """The spec names `RateLimited` specifically -- `Overloaded` propagates
    immediately, on the first attempt, with no retry loop at all.
    """
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise Overloaded("busy")

    with pytest.raises(Overloaded):
        await call_with_backoff(fn)
    assert calls == 1
