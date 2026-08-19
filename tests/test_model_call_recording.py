"""`ModelCall` is written on every path (PROJECT_SPEC.md §M2).

Real, fake, cassette-record and cassette-replay all persist a `ModelCall`
row with tokens and cost -- zero cost for fakes is fine, a missing row is
not. This test exercises all four dispatch paths through the same shared
call path (`ModelClient`) and asserts exactly one new row per dispatch.

(The parse-failure case -- "a response that was billed but failed to parse
still gets a row" -- is exercised in `test_structured_output.py`: a
provider that never produces parseable output still ends up with two
`ModelCall` rows, which could only happen if recording runs from a
`finally`, not after a successful parse.)
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.models import ModelCall
from sul.providers.anthropic import AnthropicProvider
from sul.providers.base import Message
from sul.providers.cassette import CassetteTransport
from sul.providers.client import ModelClient
from sul.providers.fake import FakeProvider


def _anthropic_mock_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": "hello from the mock"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 3},
        },
    )


def _must_not_touch_network(
    request: httpx.Request,
) -> httpx.Response:  # pragma: no cover
    raise AssertionError("cassette replay must not touch the network")


@pytest.mark.asyncio
async def test_one_model_call_row_per_dispatch_across_all_four_paths(
    session_factory: sessionmaker[Session],
    study_and_run: tuple[int, int],
    cassette_dir: Path,
) -> None:
    _study_id, run_id = study_and_run

    def _row_count() -> int:
        with session_factory() as session:
            return session.query(ModelCall).filter(ModelCall.run_id == run_id).count()

    assert _row_count() == 0

    # --- 1. fake ---
    fake_client = ModelClient(
        FakeProvider(), "fake", session_factory, agent=AgentRole.PERSONA, run_id=run_id
    )
    await fake_client.complete(
        messages=[Message(role="user", content="hi")],
        model="fake-1",
        temperature=0.0,
        max_tokens=50,
        seed=1,
    )
    assert _row_count() == 1

    # --- 2. cassette-record: a real adapter, transport wrapped for recording ---
    record_provider = AnthropicProvider(
        "sentinel-key",
        transport=CassetteTransport(
            httpx.MockTransport(_anthropic_mock_handler), cassette_dir, record=True
        ),
    )
    record_client = ModelClient(
        record_provider,
        "anthropic",
        session_factory,
        agent=AgentRole.PERSONA,
        run_id=run_id,
    )
    await record_client.complete(
        messages=[Message(role="user", content="hi")],
        model="claude-opus-5",
        temperature=0.0,
        max_tokens=50,
        seed=1,
    )
    assert _row_count() == 2
    assert list(cassette_dir.glob("*.json")), (
        "recording should have written a cassette file"
    )

    # --- 3. cassette-replay: same request, transport that would fail if hit ---
    replay_provider = AnthropicProvider(
        "sentinel-key",
        transport=CassetteTransport(
            httpx.MockTransport(_must_not_touch_network), cassette_dir, record=False
        ),
    )
    replay_client = ModelClient(
        replay_provider,
        "anthropic",
        session_factory,
        agent=AgentRole.PERSONA,
        run_id=run_id,
    )
    await replay_client.complete(
        messages=[Message(role="user", content="hi")],
        model="claude-opus-5",
        temperature=0.0,
        max_tokens=50,
        seed=1,
    )
    assert _row_count() == 3

    # --- 4. "real": SDK over a mock transport directly, no cassette layer ---
    live_provider = AnthropicProvider(
        "sentinel-key", transport=httpx.MockTransport(_anthropic_mock_handler)
    )
    live_client = ModelClient(
        live_provider,
        "anthropic",
        session_factory,
        agent=AgentRole.PERSONA,
        run_id=run_id,
    )
    await live_client.complete(
        messages=[Message(role="user", content="hi")],
        model="claude-opus-5",
        temperature=0.0,
        max_tokens=50,
        seed=1,
    )
    assert _row_count() == 4
