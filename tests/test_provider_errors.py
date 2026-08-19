"""Each adapter maps its own provider's failures onto the shared
`ProviderError` hierarchy (PROJECT_SPEC.md §M2): `RateLimited`,
`Overloaded`, `BadRequest`, `Refused`. Exercised against `AnthropicProvider`
over an `httpx.MockTransport` -- no network, and no dependency on a live
API's actual current behaviour, only on documented status codes.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from sul.providers.anthropic import AnthropicProvider
from sul.providers.base import BadRequest, Message, Overloaded, RateLimited, Refused


def _error_response(status_code: int, error_type: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"type": "error", "error": {"type": error_type, "message": error_type}},
    )


def _success_response(*, stop_reason: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": "declined"}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 1},
        },
    )


async def _complete_with(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    provider = AnthropicProvider("sentinel-key", transport=httpx.MockTransport(handler))
    await provider.complete(
        messages=[Message(role="user", content="hi")],
        model="claude-opus-5",
        temperature=0.0,
        max_tokens=50,
        seed=None,
    )


@pytest.mark.asyncio
async def test_429_maps_to_rate_limited() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_response(429, "rate_limit_error")

    with pytest.raises(RateLimited):
        await _complete_with(handler)


@pytest.mark.asyncio
async def test_529_maps_to_overloaded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_response(529, "overloaded_error")

    with pytest.raises(Overloaded):
        await _complete_with(handler)


@pytest.mark.asyncio
async def test_400_maps_to_bad_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _error_response(400, "invalid_request_error")

    with pytest.raises(BadRequest):
        await _complete_with(handler)


@pytest.mark.asyncio
async def test_refusal_stop_reason_maps_to_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _success_response(stop_reason="refusal")

    with pytest.raises(Refused):
        await _complete_with(handler)
