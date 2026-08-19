"""The provider abstraction: every LLM call in this codebase goes through
one of these (CLAUDE.md: "Every LLM call goes through the provider
abstraction. No direct SDK calls in business logic.").

`sul.providers.client.ModelClient` is the shared call path — the budget
gate, `ModelCall` recording, and the one bounded structured-output repair
turn all live there, not in the individual adapters.
"""

from __future__ import annotations

from sul.providers.base import (
    BadRequest,
    Completion,
    LLMProvider,
    Message,
    Overloaded,
    ProviderError,
    RateLimited,
    Refused,
    Usage,
    estimate_input_tokens,
)
from sul.providers.budget import BudgetExceeded, BudgetGuard
from sul.providers.cassette import CassetteCore, CassetteMissError, CassetteTransport
from sul.providers.client import ModelClient, StructuredOutputError
from sul.providers.fake import FakeProvider

__all__ = [
    "BadRequest",
    "BudgetExceeded",
    "BudgetGuard",
    "CassetteCore",
    "CassetteMissError",
    "CassetteTransport",
    "Completion",
    "FakeProvider",
    "LLMProvider",
    "Message",
    "ModelClient",
    "Overloaded",
    "ProviderError",
    "RateLimited",
    "Refused",
    "StructuredOutputError",
    "Usage",
    "estimate_input_tokens",
]
