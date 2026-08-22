"""`sul run --provider <name>`'s provider selection.

**Deliberately separate from `sul.validity.harness.run_validity_harness`'s
own two-member allow-list** (PROJECT_SPEC.md §M6 Deviation 7: `FakeProvider`
and a cassette-backed `AnthropicProvider`, and nothing else, structurally
enforced there). `sul run` may legitimately dispatch to any of this
project's real adapters when a user names one on the command line -- that is
the whole point of the command -- while `sul validate` must never be
pointable at a live provider by a flag at all. Fusing the two allow-lists
into one would widen §M6 Deviation 7's boundary; this module exists so that
never has to happen.
"""

from __future__ import annotations

from sul.config import Settings
from sul.providers.base import LLMProvider
from sul.providers.fake import FakeProvider

SUPPORTED_PROVIDERS: tuple[str, ...] = ("fake", "anthropic", "openai", "gemini")


class UnknownProviderError(ValueError):
    """`name` is not one of `SUPPORTED_PROVIDERS` at all."""


class ProviderNotConfiguredError(RuntimeError):
    """`name` is recognised but its API key is not set in `Settings`."""


def build_provider(name: str, settings: Settings) -> LLMProvider:
    """Construct the real provider adapter `name` refers to (or `FakeProvider`
    for `"fake"`). Concrete adapters are imported lazily, inside each branch
    -- `sul run` (which needs this) is the only CLI command allowed to import
    them at all; nothing agent- or validity-bound ever does (see
    `tests/test_agent_module_hygiene.py` and `sul.validity.sentinel`).
    """
    if name == "fake":
        return FakeProvider()
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ProviderNotConfiguredError(
                "ANTHROPIC_API_KEY is not set -- 'sul run --provider anthropic' "
                "needs a real key (set it in .env or the environment)"
            )
        from sul.providers.anthropic import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key)
    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfiguredError(
                "OPENAI_API_KEY is not set -- 'sul run --provider openai' needs "
                "a real key (set it in .env or the environment)"
            )
        from sul.providers.openai import OpenAIProvider

        return OpenAIProvider(settings.openai_api_key)
    if name == "gemini":
        if not settings.gemini_api_key:
            raise ProviderNotConfiguredError(
                "GEMINI_API_KEY is not set -- 'sul run --provider gemini' needs "
                "a real key (set it in .env or the environment)"
            )
        from sul.providers.gemini import GeminiProvider

        return GeminiProvider(settings.gemini_api_key)
    raise UnknownProviderError(
        f"unknown provider {name!r}; choose one of {SUPPORTED_PROVIDERS}"
    )


__all__ = [
    "SUPPORTED_PROVIDERS",
    "ProviderNotConfiguredError",
    "UnknownProviderError",
    "build_provider",
]
