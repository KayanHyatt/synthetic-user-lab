"""Gemini adapter — the real Gemini API via the official `google-genai` SDK.

Like Anthropic, `google-genai` accepts a plain `httpx.AsyncClient` for its
transport (via `HttpOptions.httpx_async_client`), so `CassetteTransport`
(the httpx-flavoured one, not the httpx2 one OpenAI needs) applies unchanged.
"""

from __future__ import annotations

import httpx
from google import genai
from google.genai import errors, types
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

DEFAULT_MODEL = "gemini-2.5-pro"

_REFUSAL_FINISH_REASONS = {
    types.FinishReason.SAFETY,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.SPII,
}


class GeminiProvider:
    """`LLMProvider` backed by the real Gemini API.

    `response_schema` is accepted but not enforced API-side, for the same
    reason as the other real adapters: validation and the one bounded
    repair turn both live in `sul.providers.client.ModelClient`.
    """

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        http_options = None
        if transport is not None:
            http_options = types.HttpOptions(
                httpx_async_client=httpx.AsyncClient(transport=transport)
            )
        self._client = genai.Client(api_key=api_key, http_options=http_options)

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
        system_instruction = "\n\n".join(
            m.content for m in messages if m.role == "system"
        )
        contents = [
            types.Content(
                role="model" if m.role == "assistant" else "user",
                parts=[types.Part(text=m.content)],
            )
            for m in messages
            if m.role != "system"
        ]

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
            seed=seed,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.ClientError as exc:
            if exc.code == 429:
                raise RateLimited(str(exc)) from exc
            if exc.code == 400:
                raise BadRequest(str(exc)) from exc
            raise ProviderError(str(exc)) from exc
        except errors.ServerError as exc:
            if exc.code in (503, 529):
                raise Overloaded(str(exc)) from exc
            raise ProviderError(str(exc)) from exc

        candidate = response.candidates[0] if response.candidates else None
        finish_reason = candidate.finish_reason if candidate else None
        if finish_reason in _REFUSAL_FINISH_REASONS:
            raise Refused(f"Gemini declined: {finish_reason}")

        usage = response.usage_metadata

        return Completion(
            text=response.text or "",
            usage=Usage(
                tokens_in=usage.prompt_token_count
                if usage and usage.prompt_token_count
                else 0,
                tokens_out=usage.candidates_token_count
                if usage and usage.candidates_token_count
                else 0,
            ),
            model=response.model_version or model,
            stop_reason=str(finish_reason) if finish_reason else None,
        )


__all__ = ["DEFAULT_MODEL", "GeminiProvider"]
