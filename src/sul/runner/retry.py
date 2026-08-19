"""Exponential backoff with jitter on `RateLimited` (PROJECT_SPEC.md §M4).

This is timing/scheduling logic, not synthesis: unlike `sul.runner.seeds`, the
jitter here does not feed into what gets sent to a provider or into
`ModelCall.seed`, so it has no bearing on transcript reproducibility -- two
runs that both eventually succeed produce byte-identical transcripts
regardless of how many times a `RateLimited` retry loop spun in between. It is
therefore fine (and simpler) for the default jitter source to be an ordinary
`random.Random` rather than a derived substream; callers that want
deterministic *test* assertions on the actual delays pass their own seeded
`random.Random`.

`Overloaded` is intentionally not retried here: the spec names `RateLimited`
specifically, and conflating the two would silently broaden what counts as
"the failure mode of a filled queue" without evidence that the same retry
strategy is correct for both.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from sul.providers.base import RateLimited

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY_SECONDS = 0.25
DEFAULT_JITTER_SECONDS = 0.25


async def call_with_backoff[T](
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    jitter_seconds: float = DEFAULT_JITTER_SECONDS,
    rng: random.Random | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Call `fn()`, retrying on `RateLimited` with exponential backoff plus
    jitter, up to `max_attempts` total attempts.

    `sleep` is injectable so tests can assert on computed delays without
    actually waiting on them (see `tests/test_retry.py`).
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")

    active_rng = rng if rng is not None else random.Random()

    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except RateLimited:
            if attempt == max_attempts:
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            delay += active_rng.uniform(0.0, jitter_seconds)
            await sleep(delay)

    # Unreachable: the loop above always either returns or re-raises on the
    # final attempt.
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = [
    "DEFAULT_BASE_DELAY_SECONDS",
    "DEFAULT_JITTER_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "call_with_backoff",
]
