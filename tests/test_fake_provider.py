"""FakeProvider discriminates rather than recites (PROJECT_SPEC.md §M2).

Same (model, prompt, schema, seed) -> byte-identical output. Change any one
of those four -> a different output. A canned string would pass the
repeat-call test and the prompt-change test; it would not survive the
schema-change test, which is why that one exists separately -- a digest
keyed on the prompt alone (ignoring `response_schema`) would happily
produce the exact same JSON text for two structurally different schemas.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from sul.providers.base import Message
from sul.providers.fake import FakeProvider


class Verdict(BaseModel):
    approved: bool
    reason: str


class RiskScore(BaseModel):
    score: int
    factors: list[str]


@pytest.mark.asyncio
async def test_repeat_call_is_byte_identical() -> None:
    provider = FakeProvider()
    messages = [Message(role="user", content="Evaluate this onboarding flow.")]

    first = await provider.complete(
        messages=messages, model="fake-1", temperature=0.0, max_tokens=200, seed=42
    )
    second = await provider.complete(
        messages=messages, model="fake-1", temperature=0.0, max_tokens=200, seed=42
    )

    assert first.text == second.text
    assert first.usage == second.usage


@pytest.mark.asyncio
async def test_one_word_prompt_change_changes_output() -> None:
    provider = FakeProvider()
    base = [Message(role="user", content="Evaluate this onboarding flow.")]
    changed = [Message(role="user", content="Evaluate this pricing flow.")]

    first = await provider.complete(
        messages=base, model="fake-1", temperature=0.0, max_tokens=200, seed=42
    )
    second = await provider.complete(
        messages=changed, model="fake-1", temperature=0.0, max_tokens=200, seed=42
    )

    assert first.text != second.text


@pytest.mark.asyncio
async def test_seed_change_changes_output() -> None:
    provider = FakeProvider()
    messages = [Message(role="user", content="Evaluate this onboarding flow.")]

    first = await provider.complete(
        messages=messages, model="fake-1", temperature=0.0, max_tokens=200, seed=1
    )
    second = await provider.complete(
        messages=messages, model="fake-1", temperature=0.0, max_tokens=200, seed=2
    )

    assert first.text != second.text


@pytest.mark.asyncio
async def test_same_prompt_and_seed_different_schema_yields_different_shapes() -> None:
    """The test a canned-string or prompt-only digest cannot pass: identical
    model/prompt/seed, but two structurally different schemas, must produce
    two differently-shaped valid instances -- not the same text twice.
    """
    provider = FakeProvider()
    messages = [Message(role="user", content="Assess this signup form.")]

    verdict_completion = await provider.complete(
        messages=messages,
        model="fake-1",
        temperature=0.0,
        max_tokens=200,
        seed=7,
        response_schema=Verdict,
    )
    risk_completion = await provider.complete(
        messages=messages,
        model="fake-1",
        temperature=0.0,
        max_tokens=200,
        seed=7,
        response_schema=RiskScore,
    )

    assert verdict_completion.text != risk_completion.text

    verdict = Verdict.model_validate_json(verdict_completion.text)
    risk = RiskScore.model_validate_json(risk_completion.text)

    assert isinstance(verdict.approved, bool)
    assert isinstance(verdict.reason, str)
    assert isinstance(risk.score, int)
    assert isinstance(risk.factors, list)
    assert all(isinstance(f, str) for f in risk.factors)


@pytest.mark.asyncio
async def test_schema_output_is_deterministic_too() -> None:
    provider = FakeProvider()
    messages = [Message(role="user", content="Assess this signup form.")]

    first = await provider.complete(
        messages=messages,
        model="fake-1",
        temperature=0.0,
        max_tokens=200,
        seed=7,
        response_schema=Verdict,
    )
    second = await provider.complete(
        messages=messages,
        model="fake-1",
        temperature=0.0,
        max_tokens=200,
        seed=7,
        response_schema=Verdict,
    )

    assert first.text == second.text
