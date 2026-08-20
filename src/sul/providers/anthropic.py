"""Anthropic adapter — the real Claude Messages API via the official SDK.

Uses an injected `httpx.AsyncClient` transport so `CassetteTransport` (see
`sul.providers.cassette`) can record/replay traffic at the HTTP layer,
uniformly with the other adapters.
"""

from __future__ import annotations

from typing import Any

import anthropic
import httpx
from anthropic import transform_schema
from anthropic.types import MessageParam
from pydantic import BaseModel

from sul.providers.base import (
    BadRequest,
    Completion,
    Message,
    Overloaded,
    ProviderError,
    RateLimited,
    Refused,
    Usage,
)

DEFAULT_MODEL = "claude-opus-5"

# Models that reject sampling parameters outright (400) rather than ignoring
# them: Claude 4.6+ removed `temperature`/`top_p`/`top_k` (PROJECT_SPEC.md §M6
# Deviation 10 -- found via a real recording pass, §M6 Deviation 9, that made
# zero real Analyst calls and so never reached this). Matched by prefix, not
# an exact-string allow-list, so a dated snapshot of one of these families
# (e.g. a future `claude-opus-5-<date>`) is still caught. `claude-haiku-4-5`
# is deliberately absent -- it still accepts `temperature`.
_NO_SAMPLING_PARAMS_MODEL_PREFIXES: tuple[str, ...] = (
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)


def _accepts_temperature(model: str) -> bool:
    return not model.startswith(_NO_SAMPLING_PARAMS_MODEL_PREFIXES)


class AnthropicProvider:
    """`LLMProvider` backed by the real Anthropic API.

    `seed` is accepted for interface uniformity with `FakeProvider` (and
    because the shared call path in `sul.providers.client` hashes it into
    `ModelCall.prompt_hash` regardless of provider) but is not forwarded to
    the Anthropic Messages API, which has no seed parameter — real Claude
    completions are not seed-reproducible the way FakeProvider's synthetic
    ones are.

    `response_schema`, when given, is turned into an `output_config.format`
    JSON-schema constraint on the request (PROJECT_SPEC.md §M6 Deviation
    10) -- the API rejects a response that doesn't validate, so the text
    block this adapter returns is guaranteed schema-valid JSON before
    `sul.providers.client.ModelClient` ever calls `model_validate_json` on
    it. This does not replace that shared call path's one bounded repair
    turn: it stays live for `max_tokens` truncation and for the other
    adapters (`sul.providers.openai`, `.gemini`), which still ignore
    `response_schema` entirely, exactly as this class's docstring used to
    say *this* adapter did. See §M2's implementation note for the pointer to
    this deviation.
    """

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        http_client = (
            httpx.AsyncClient(transport=transport) if transport is not None else None
        )
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, http_client=http_client
        )

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns: list[MessageParam] = [
            MessageParam(role=m.role, content=m.content)
            for m in messages
            if m.role != "system"
        ]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": turns,
        }
        if system:
            kwargs["system"] = system
        if _accepts_temperature(model):
            kwargs["temperature"] = temperature
        if response_schema is not None:
            kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": transform_schema(response_schema),
                }
            }

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise RateLimited(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code == 400:
                raise BadRequest(str(exc)) from exc
            if exc.status_code in (529, 503):
                raise Overloaded(str(exc)) from exc
            raise ProviderError(str(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(str(exc)) from exc

        if response.stop_reason == "refusal":
            raise Refused(f"Anthropic refused: {response.stop_details}")

        text = "".join(block.text for block in response.content if block.type == "text")

        return Completion(
            text=text,
            usage=Usage(
                tokens_in=response.usage.input_tokens,
                tokens_out=response.usage.output_tokens,
            ),
            model=response.model,
            stop_reason=response.stop_reason,
        )


__all__ = ["DEFAULT_MODEL", "AnthropicProvider"]
