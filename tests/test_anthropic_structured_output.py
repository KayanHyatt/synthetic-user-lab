"""PROJECT_SPEC.md §M6 Deviation 10: `AnthropicProvider` now turns a
`response_schema` into an `output_config.format` JSON-schema constraint on
the wire request, rather than doing nothing with it (the pre-deviation
behaviour -- see this module's own docstring history in
PROJECT_SPEC.md §M2/§M6). Driven entirely through `httpx.MockTransport`, the
same no-network technique `tests/test_cassettes.py` and
`tests/test_validity_cassette_plumbing.py` already use -- never a live call.

The recursive unsupported-keyword assertion below is the one that would
otherwise only ever fail as a live 400: `output_config.format` rejects
`minLength`/`minimum`/etc. anywhere in the schema tree, and the SDK's
`transform_schema` is what relocates them into field descriptions instead.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sul.providers.anthropic import AnthropicProvider
from sul.providers.base import Message
from sul.schemas.agents import (
    ModeratorFollowup,
    PersonaReply,
    build_analyst_response_schema,
)
from sul.validity.schemas import (
    ChoiceProbeContext,
    FramingProbeReply,
    build_choice_probe_schema,
)

_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
)


def _assert_no_unsupported_keywords(node: object) -> None:
    """Walk the whole schema tree -- `output_config.format` rejects these
    keywords anywhere, not just at the top level, and a nested `$defs` entry
    is exactly where pydantic tends to put a `Field(ge=..., le=...)`
    constraint on a non-root model.
    """
    if isinstance(node, dict):
        for key in node:
            assert key not in _UNSUPPORTED_KEYWORDS, (
                f"unsupported JSON Schema keyword {key!r} survived into the "
                f"request: {node!r}"
            )
        for value in node.values():
            _assert_no_unsupported_keywords(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_unsupported_keywords(item)


def _mock_ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5",
            "content": [{"type": "text", "text": "{}"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 2},
        },
    )


async def _dispatch_and_capture_body(
    *, model: str, response_schema: type[Any] | None
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _mock_ok_handler(request)

    provider = AnthropicProvider(
        "sentinel-key", transport=httpx.MockTransport(_handler)
    )
    await provider.complete(
        messages=[Message(role="user", content="hello")],
        model=model,
        temperature=0.7,
        max_tokens=200,
        seed=1,
        response_schema=response_schema,
    )
    return captured["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema",
    [
        PersonaReply,
        ModeratorFollowup,
        FramingProbeReply,
        build_choice_probe_schema(("A", "B")),
        build_analyst_response_schema((1, 3, 5)),
    ],
)
async def test_response_schema_becomes_output_config_json_schema(
    schema: type[Any],
) -> None:
    body = await _dispatch_and_capture_body(
        model="claude-haiku-4-5", response_schema=schema
    )

    output_format = body["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    _assert_no_unsupported_keywords(output_format["schema"])


@pytest.mark.asyncio
async def test_additional_properties_false_on_every_object_node() -> None:
    body = await _dispatch_and_capture_body(
        model="claude-haiku-4-5", response_schema=ChoiceProbeContext
    )
    schema = body["output_config"]["format"]["schema"]

    def _assert_objects_forbid_extra(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
            for value in node.values():
                _assert_objects_forbid_extra(value)
        elif isinstance(node, list):
            for item in node:
                _assert_objects_forbid_extra(item)

    _assert_objects_forbid_extra(schema)


@pytest.mark.asyncio
async def test_analyst_evidence_ordinals_arrive_as_a_json_schema_enum() -> None:
    schema_cls = build_analyst_response_schema((2, 4, 6))
    body = await _dispatch_and_capture_body(
        model="claude-haiku-4-5", response_schema=schema_cls
    )
    schema = body["output_config"]["format"]["schema"]

    # The Literal[2, 4, 6] field, wherever transform_schema places it
    # (top-level or under $defs), must show up as an explicit enum of
    # exactly those three ordinals -- not a bare "integer" the model could
    # fill with any number.
    found: list[list[int]] = []

    def _collect_enums(node: object) -> None:
        if isinstance(node, dict):
            if "enum" in node and all(isinstance(v, int) for v in node["enum"]):
                found.append(node["enum"])
            for value in node.values():
                _collect_enums(value)
        elif isinstance(node, list):
            for item in node:
                _collect_enums(item)

    _collect_enums(schema)
    assert [2, 4, 6] in found


@pytest.mark.asyncio
async def test_output_config_absent_when_no_response_schema() -> None:
    body = await _dispatch_and_capture_body(
        model="claude-haiku-4-5", response_schema=None
    )
    assert "output_config" not in body


@pytest.mark.asyncio
async def test_temperature_present_for_haiku_absent_for_sonnet_and_opus() -> None:
    haiku_body = await _dispatch_and_capture_body(
        model="claude-haiku-4-5", response_schema=None
    )
    sonnet_body = await _dispatch_and_capture_body(
        model="claude-sonnet-5", response_schema=None
    )
    opus_body = await _dispatch_and_capture_body(
        model="claude-opus-5", response_schema=None
    )

    assert "temperature" in haiku_body
    assert "temperature" not in sonnet_body
    assert "temperature" not in opus_body
