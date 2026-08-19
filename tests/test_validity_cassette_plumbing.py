"""Confirm 1 in the M6 design conversation: cassette replay must work end to
end for M6's probes, proven now rather than left as an unexercised code
path. The cassette here is hand-authored -- recorded against
`httpx.MockTransport` (the same no-network technique
`tests/test_cassettes.py` already uses for the cassette layer itself), never
against a live API. This is what makes "replaying a cassette is offline"
(Confirm 1) a tested claim.

This cassette exists only to prove the plumbing works. It must never be
reachable from `sul validate` -- see `tests/test_cli_validate.py`'s
structural check that command has no flag that could point it here.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole, ArtefactKind
from sul.providers.anthropic import AnthropicProvider
from sul.providers.cassette import CassetteTransport
from sul.providers.client import ModelClient
from sul.validity.probes import run_framing_probe
from sul.validity.schemas import FramingProbeContext


def _mock_agree_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5",
            "content": [{"type": "text", "text": '{"agreement": "agree"}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 42, "output_tokens": 6},
        },
    )


@pytest.mark.asyncio
async def test_cassette_replay_works_through_the_full_probe_path(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
    study_and_run: tuple[int, int],
) -> None:
    cassette_dir = tmp_path / "plumbing_cassettes"
    cassette_dir.mkdir()
    _study_id, run_id = study_and_run

    context = FramingProbeContext(
        persona_card="You are a persona.",
        artefact_kind=ArtefactKind.HTML,
        artefact_body="<html></html>",
        framed_question="Was the pricing clear?",
    )
    model = "claude-haiku-4-5"
    temperature = 0.7
    max_tokens = 200
    seed = 4242

    recording_provider = AnthropicProvider(
        "sentinel-record-key",
        transport=CassetteTransport(
            httpx.MockTransport(_mock_agree_handler), cassette_dir, record=True
        ),
    )
    recording_client = ModelClient(
        recording_provider,
        "anthropic",
        session_factory,
        agent=AgentRole.VALIDITY_PROBE,
        run_id=run_id,
    )
    await run_framing_probe(
        client=recording_client,
        context=context,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
    )

    cassette_files = list(cassette_dir.glob("*.json"))
    assert len(cassette_files) == 1

    def _network_should_not_be_called(
        request: httpx.Request,
    ) -> httpx.Response:  # pragma: no cover
        raise AssertionError("replay must not touch the network")

    replay_provider = AnthropicProvider(
        "a-totally-different-live-key",
        transport=CassetteTransport(
            httpx.MockTransport(_network_should_not_be_called),
            cassette_dir,
            record=False,
        ),
    )
    replay_client = ModelClient(
        replay_provider,
        "anthropic",
        session_factory,
        agent=AgentRole.VALIDITY_PROBE,
        run_id=run_id,
    )
    reply = await run_framing_probe(
        client=replay_client,
        context=context,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
    )

    assert reply.agreement == "agree"
