"""Cassettes are scrubbed at write time, not read time (PROJECT_SPEC.md §M2).

The credential is redacted from both request and response *before* the
bytes reach disk. The test proves this by scanning the raw file text (not
the parsed JSON object -- a scrubber that only redacts the value the parser
happens to look at could still leave a credential elsewhere in the raw
bytes) for the sentinel key, the `sk-ant-` pattern, and every sensitive
header name. It then proves scrubbing didn't break replay: the same
scrubbed cassette must still match on a fresh request, keyed on the
canonicalised body -- not on the headers that were just stripped.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest

from sul.providers.cassette import CassetteMissError, CassetteTransport

SENTINEL_KEY = "sk-ant-sentinel0000000000000000000000000000"
REQUEST_URL = "https://api.anthropic.com/v1/messages"


def _mock_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers.get("x-api-key") == SENTINEL_KEY
    return httpx.Response(
        200,
        headers={"anthropic-organization-id": "org_123"},
        json={
            "id": "msg_01",
            "model": "claude-opus-5",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello from the mock"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        },
    )


async def _record_one_cassette(
    cassette_dir: Path, *, body: Mapping[str, object]
) -> Path:
    mock_transport = httpx.MockTransport(_mock_handler)
    transport = CassetteTransport(mock_transport, cassette_dir, record=True)
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            REQUEST_URL,
            headers={
                "x-api-key": SENTINEL_KEY,
                "anthropic-version": "2023-06-01",
                "authorization": f"Bearer {SENTINEL_KEY}",
            },
            json=body,
        )
    assert response.status_code == 200

    cassette_files = list(cassette_dir.glob("*.json"))
    assert len(cassette_files) == 1
    return cassette_files[0]


@pytest.mark.asyncio
async def test_cassette_is_scrubbed_before_it_reaches_disk(cassette_dir: Path) -> None:
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}
    cassette_path = await _record_one_cassette(cassette_dir, body=body)

    raw_text = cassette_path.read_text(encoding="utf-8")

    assert "sk-ant-" not in raw_text
    assert SENTINEL_KEY not in raw_text
    for header_name in ("x-api-key", "authorization", "Authorization", "X-Api-Key"):
        assert header_name not in raw_text


@pytest.mark.asyncio
async def test_scrubbed_cassette_still_replays(cassette_dir: Path) -> None:
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}
    await _record_one_cassette(cassette_dir, body=body)

    def _network_should_not_be_called(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover
        raise AssertionError("replay must not touch the network")

    replay_transport = CassetteTransport(
        httpx.MockTransport(_network_should_not_be_called), cassette_dir, record=False
    )
    async with httpx.AsyncClient(transport=replay_transport) as client:
        response = await client.post(
            REQUEST_URL,
            headers={"x-api-key": "a-totally-different-live-key"},
            json=body,
        )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "hello from the mock"


@pytest.mark.asyncio
async def test_replay_matches_on_canonical_body_not_key_order(
    cassette_dir: Path,
) -> None:
    """A request whose JSON body has the same content but different key
    order must still hit the cassette recorded with the "original" order --
    the match key is canonicalised, not a hash of the raw bytes.
    """
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}
    await _record_one_cassette(cassette_dir, body=body)

    reordered_body = {
        "messages": [{"content": "hi", "role": "user"}],
        "model": "claude-opus-5",
    }

    def _network_should_not_be_called(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover
        raise AssertionError("replay must not touch the network")

    replay_transport = CassetteTransport(
        httpx.MockTransport(_network_should_not_be_called), cassette_dir, record=False
    )
    async with httpx.AsyncClient(transport=replay_transport) as client:
        response = await client.post(
            REQUEST_URL, headers={"x-api-key": "irrelevant"}, json=reordered_body
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_record_if_missing_replays_an_existing_cassette_without_the_network(
    cassette_dir: Path,
) -> None:
    """A second recording pass sharing a cassette dir with a first one
    (PROJECT_SPEC.md M6 two-configuration recording pass): a key already on
    disk must not re-dispatch, even though `record=True`.
    """
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}
    await _record_one_cassette(cassette_dir, body=body)

    def _network_should_not_be_called(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover
        raise AssertionError("a cached key must not be re-dispatched")

    transport = CassetteTransport(
        httpx.MockTransport(_network_should_not_be_called),
        cassette_dir,
        record=True,
        record_if_missing=True,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            REQUEST_URL,
            headers={"x-api-key": "a-totally-different-live-key"},
            json=body,
        )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "hello from the mock"


@pytest.mark.asyncio
async def test_record_if_missing_still_dispatches_and_writes_a_genuine_miss(
    cassette_dir: Path,
) -> None:
    """A key with no existing cassette is dispatched and written normally,
    `record_if_missing=True` notwithstanding -- it only short-circuits keys
    already on disk.
    """
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}
    transport = CassetteTransport(
        httpx.MockTransport(_mock_handler),
        cassette_dir,
        record=True,
        record_if_missing=True,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            REQUEST_URL, headers={"x-api-key": SENTINEL_KEY}, json=body
        )

    assert response.status_code == 200
    assert len(list(cassette_dir.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_record_without_record_if_missing_still_always_overwrites(
    cassette_dir: Path,
) -> None:
    """Default behaviour (`record_if_missing=False`, the existing default)
    is unchanged: `record=True` always re-dispatches and overwrites, even
    when a cassette for that key already exists.
    """
    body = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}
    await _record_one_cassette(cassette_dir, body=body)

    called = False

    def _second_handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(
            200,
            json={
                "id": "msg_02",
                "model": "claude-opus-5",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "second response"}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    transport = CassetteTransport(
        httpx.MockTransport(_second_handler), cassette_dir, record=True
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            REQUEST_URL,
            headers={"x-api-key": SENTINEL_KEY},
            json=body,
        )

    assert called
    assert response.json()["content"][0]["text"] == "second response"


@pytest.mark.asyncio
async def test_replay_miss_raises_and_never_touches_the_network(
    cassette_dir: Path,
) -> None:
    def _network_should_not_be_called(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover
        raise AssertionError(
            "a cassette miss must raise, not fall through to the network"
        )

    transport = CassetteTransport(
        httpx.MockTransport(_network_should_not_be_called), cassette_dir, record=False
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(CassetteMissError):
            await client.post(
                REQUEST_URL, json={"model": "claude-opus-5", "messages": []}
            )
