"""Anthropic adapter — the real Claude Messages API via the official SDK.

Uses an injected `httpx.AsyncClient` transport so `CassetteTransport` (see
`sul.providers.cassette`) can record/replay traffic at the HTTP layer,
uniformly with the other adapters.
"""

from __future__ import annotations

import anthropic
import httpx
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


class AnthropicProvider:
    """`LLMProvider` backed by the real Anthropic API.

    `seed` is accepted for interface uniformity with `FakeProvider` (and
    because the shared call path in `sul.providers.client` hashes it into
    `ModelCall.prompt_hash` regardless of provider) but is not forwarded to
    the Anthropic Messages API, which has no seed parameter — real Claude
    completions are not seed-reproducible the way FakeProvider's synthetic
    ones are.

    `response_schema` is likewise accepted but not enforced API-side: the
    shared call path (`sul.providers.client.ModelClient`) validates the
    returned text against the schema and drives the one bounded repair turn
    itself, so every adapter behaves identically regardless of whether the
    underlying API has a native structured-output mode.
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

        try:
            if system:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=turns,
                )
            else:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=turns,
                )
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
