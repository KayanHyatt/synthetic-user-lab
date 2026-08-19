"""OpenAI adapter — the real Chat Completions API via the official SDK.

The OpenAI SDK (3.x) vendors its own httpx fork, importable as `httpx2`, and
its `http_client` / transport parameters require that fork's classes rather
than plain `httpx`'s — see the module docstring in `sul.providers.cassette`
for why `CassetteCore` (not `CassetteTransport`, which is httpx-specific) is
what this adapter wraps its transport with.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx2
import openai
from openai.types.chat import ChatCompletionMessageParam
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
from sul.providers.cassette import CassetteCore

DEFAULT_MODEL = "gpt-5"


class CassetteTransportHttpx2(httpx2.AsyncBaseTransport):
    """`CassetteCore` wrapped for the OpenAI SDK's vendored httpx fork."""

    def __init__(
        self,
        inner: httpx2.AsyncBaseTransport,
        cassette_dir: Path,
        *,
        record: bool = False,
    ) -> None:
        self._core = CassetteCore(
            inner, cassette_dir, record=record, response_cls=httpx2.Response
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response: httpx2.Response = await self._core.handle(request)
        return response


class OpenAIProvider:
    """`LLMProvider` backed by the real OpenAI Chat Completions API.

    Unlike Anthropic, OpenAI's API does accept a `seed` parameter, so it is
    forwarded — but OpenAI documents this as best-effort determinism, not a
    guarantee, so downstream code should still treat real OpenAI calls as
    non-reproducible the way FakeProvider's are.

    `response_schema` is accepted but not enforced API-side, for the same
    reason as `sul.providers.anthropic.AnthropicProvider`: validation and
    the one bounded repair turn both live in `sul.providers.client.ModelClient`.
    """

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        http_client = (
            httpx2.AsyncClient(transport=transport) if transport is not None else None
        )
        self._client = openai.AsyncOpenAI(api_key=api_key, http_client=http_client)

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
        # `m.role` spans "system"/"user"/"assistant", which map onto three
        # different ChatCompletionMessageParam TypedDict variants -- `cast`
        # rather than `# type: ignore`, since the dict shape genuinely is
        # correct for whichever variant `m.role` picks out at runtime.
        turns: list[ChatCompletionMessageParam] = [
            cast(ChatCompletionMessageParam, {"role": m.role, "content": m.content})
            for m in messages
        ]

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=turns,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
        except openai.RateLimitError as exc:
            raise RateLimited(str(exc)) from exc
        except openai.APIStatusError as exc:
            if exc.status_code == 400:
                raise BadRequest(str(exc)) from exc
            if exc.status_code in (529, 503):
                raise Overloaded(str(exc)) from exc
            raise ProviderError(str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(str(exc)) from exc

        choice = response.choices[0]
        if choice.message.refusal:
            raise Refused(choice.message.refusal)

        return Completion(
            text=choice.message.content or "",
            usage=Usage(
                tokens_in=response.usage.prompt_tokens if response.usage else 0,
                tokens_out=response.usage.completion_tokens if response.usage else 0,
            ),
            model=response.model,
            stop_reason=choice.finish_reason,
        )


__all__ = ["DEFAULT_MODEL", "CassetteTransportHttpx2", "OpenAIProvider"]
