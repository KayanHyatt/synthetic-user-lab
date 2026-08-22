"""`sul.providers.factory.build_provider` (PROJECT_SPEC.md §M7): `sul run`'s
own provider selection, deliberately separate from `run_validity_harness`'s
two-member allow-list (§M6 Deviation 7).
"""

from __future__ import annotations

from typing import Any

import pytest

from sul.config import Settings
from sul.providers.factory import (
    ProviderNotConfiguredError,
    UnknownProviderError,
    build_provider,
)
from sul.providers.fake import FakeProvider


def _settings(**overrides: Any) -> Settings:
    """`Settings` with no `.env` file read -- this repo's own `.env` may
    carry a real `ANTHROPIC_API_KEY` for local dev, and these tests need to
    control exactly what's configured, not inherit whatever's on this
    machine. `_env_file` is pydantic-settings' own init-time override
    (undeclared as a regular field, hence the one `type: ignore` here rather
    than one per call site below).
    """
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_fake_needs_no_settings_at_all() -> None:
    settings = _settings()
    provider = build_provider("fake", settings)
    assert isinstance(provider, FakeProvider)


def test_unknown_provider_name_is_rejected() -> None:
    settings = _settings()
    with pytest.raises(UnknownProviderError, match="nonsense"):
        build_provider("nonsense", settings)


def test_anthropic_without_a_key_raises_a_clear_error() -> None:
    settings = _settings(anthropic_api_key=None)
    with pytest.raises(ProviderNotConfiguredError, match="ANTHROPIC_API_KEY"):
        build_provider("anthropic", settings)


def test_openai_without_a_key_raises_a_clear_error() -> None:
    settings = _settings(openai_api_key=None)
    with pytest.raises(ProviderNotConfiguredError, match="OPENAI_API_KEY"):
        build_provider("openai", settings)


def test_gemini_without_a_key_raises_a_clear_error() -> None:
    settings = _settings(gemini_api_key=None)
    with pytest.raises(ProviderNotConfiguredError, match="GEMINI_API_KEY"):
        build_provider("gemini", settings)


def test_anthropic_with_a_key_constructs_the_real_adapter() -> None:
    from sul.providers.anthropic import AnthropicProvider

    settings = _settings(anthropic_api_key="sk-ant-test-only")
    provider = build_provider("anthropic", settings)
    assert isinstance(provider, AnthropicProvider)
