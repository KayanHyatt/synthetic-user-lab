"""The provider abstraction every LLM call goes through (CLAUDE.md: "Every
LLM call goes through the provider abstraction. No direct SDK calls in
business logic.").

`LLMProvider` is the spec's Protocol (PROJECT_SPEC.md §M2) verbatim. Adapters
(`sul.providers.anthropic`, `.openai`, `.gemini`, `.fake`) each implement it
and translate their own failure modes onto the shared `ProviderError`
hierarchy below, so calling code never has to know which vendor it is
talking to.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class Message(BaseModel):
    """One turn in a conversation sent to a provider."""

    role: Literal["system", "user", "assistant"]
    content: str


class Usage(BaseModel):
    """Token counts a provider reports for a single call."""

    tokens_in: int
    tokens_out: int


class Completion(BaseModel):
    """A provider's response to one `complete()` call."""

    text: str
    usage: Usage
    model: str
    stop_reason: str | None = None


class ProviderError(Exception):
    """Base of the shared error hierarchy every adapter maps its own errors onto."""


class RateLimited(ProviderError):
    """The provider rejected the call because of a rate limit (HTTP 429)."""


class Overloaded(ProviderError):
    """The provider is temporarily overloaded (e.g. HTTP 529)."""


class BadRequest(ProviderError):
    """The request itself was invalid (HTTP 400)."""


class Refused(ProviderError):
    """The provider declined to answer (a policy refusal, not a transport failure)."""


class LLMProvider(Protocol):
    """The one interface every LLM call in this codebase is made through."""

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion: ...


# Conservative, offline heuristic: ~4 characters per token, plus a small
# fixed overhead per message for role/formatting tokens. This is what the
# pre-call budget gate estimates against — it is deliberately not a network
# call to a tokenizer endpoint. M4 may replace it with a provider's real
# `count_tokens` API without changing anything downstream of the estimate.
_CHARS_PER_TOKEN = 4
_PER_MESSAGE_OVERHEAD_TOKENS = 4


def estimate_input_tokens(messages: list[Message]) -> int:
    """Estimate the input token count of `messages`, rounding up."""
    total_chars = sum(len(m.content) for m in messages)
    char_tokens = -(-total_chars // _CHARS_PER_TOKEN)  # ceil division
    return char_tokens + _PER_MESSAGE_OVERHEAD_TOKENS * len(messages)
