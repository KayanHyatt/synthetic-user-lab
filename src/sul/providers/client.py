"""The shared call path every provider goes through.

This is where the spec's per-call requirements are actually enforced,
uniformly across `FakeProvider`, cassette-backed real providers, and live
real providers: the budget gate runs before dispatch (`BudgetGuard`,
checked first — nothing is ever sent once it raises), a `ModelCall` row is
written for every dispatch attempt (including one that fails to parse —
recorded from a `finally`, not after a successful parse), and structured
output gets exactly one bounded repair turn before giving up
(PROJECT_SPEC.md §M2).

Nothing outside this module should ever call `provider.complete(...)`
directly — that would bypass the budget gate and the `ModelCall` audit
trail, which is the whole point of "every LLM call goes through the
provider abstraction" (CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import time
from typing import TypeVar, overload

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from sul.db import session_scope
from sul.enums import AgentRole
from sul.hashing import config_hash
from sul.models import ModelCall
from sul.pricing import cost_for, estimate_cost, price_for
from sul.providers.base import Completion, LLMProvider, Message, estimate_input_tokens
from sul.providers.budget import BudgetGuard

T = TypeVar("T", bound=BaseModel)

_REPAIR_INSTRUCTION = (
    "Your previous output failed validation against the required schema. "
    "Error: {error}\n\n"
    "Original output:\n{raw}\n\n"
    "Reply again with ONLY output that validates against the schema. "
    "No commentary, no markdown fences."
)


class StructuredOutputError(Exception):
    """Parsing a provider's response into the requested schema failed after
    the original attempt and one repair turn. Carries the raw text of the
    final attempt — never a default, an empty model, a regex fallback, or a
    silent retry loop.
    """

    def __init__(self, raw_text: str, schema: type[BaseModel], attempts: int) -> None:
        self.raw_text = raw_text
        self.schema = schema
        self.attempts = attempts
        super().__init__(
            f"Could not parse output into {schema.__name__} after {attempts} "
            f"attempt(s). Raw text: {raw_text!r}"
        )


class ModelClient:
    """The one path every LLM call in this codebase takes.

    budget gate -> dispatch -> record ModelCall -> parse (with one repair
    turn on failure).
    """

    def __init__(
        self,
        provider: LLMProvider,
        provider_name: str,
        session_factory: sessionmaker[Session],
        *,
        agent: AgentRole,
        budget: BudgetGuard | None = None,
        run_id: int | None = None,
    ) -> None:
        self._provider = provider
        self._provider_name = provider_name
        self._session_factory = session_factory
        self._agent = agent
        self._budget = budget
        self._run_id = run_id

    @overload
    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: None = None,
    ) -> str: ...

    @overload
    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[T],
    ) -> T: ...

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[T] | None = None,
    ) -> T | str:
        completion = await self._dispatch(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            response_schema=response_schema,
        )

        if response_schema is None:
            return completion.text

        try:
            return response_schema.model_validate_json(completion.text)
        except ValidationError as first_error:
            repair_messages = [
                *messages,
                Message(role="assistant", content=completion.text),
                Message(
                    role="user",
                    content=_REPAIR_INSTRUCTION.format(
                        error=first_error, raw=completion.text
                    ),
                ),
            ]
            repaired = await self._dispatch(
                messages=repair_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
                response_schema=response_schema,
            )
            try:
                return response_schema.model_validate_json(repaired.text)
            except ValidationError as second_error:
                raise StructuredOutputError(
                    raw_text=repaired.text, schema=response_schema, attempts=2
                ) from second_error

    async def _dispatch(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[BaseModel] | None,
    ) -> Completion:
        price = price_for(self._provider_name, model)
        estimated_tokens_in = estimate_input_tokens(messages)
        estimate = estimate_cost(price, estimated_tokens_in, max_tokens)

        if self._budget is not None:
            # Gate runs, and must raise, before the provider is ever touched.
            await asyncio.to_thread(self._budget.check, estimate)

        prompt_hash = config_hash(
            {
                "model": model,
                "messages": [m.model_dump() for m in messages],
                "schema": response_schema.model_json_schema()
                if response_schema
                else None,
                "seed": seed,
            }
        )

        started = time.monotonic()
        completion: Completion | None = None
        try:
            completion = await self._provider.complete(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
                response_schema=response_schema,
            )
            return completion
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            tokens_in = (
                completion.usage.tokens_in if completion else estimated_tokens_in
            )
            tokens_out = completion.usage.tokens_out if completion else 0
            cost_usd = cost_for(price, tokens_in, tokens_out) if completion else 0.0
            await asyncio.to_thread(
                self._record,
                model=model,
                prompt_hash=prompt_hash,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                seed=seed,
            )

    def _record(
        self,
        *,
        model: str,
        prompt_hash: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        latency_ms: int,
        seed: int | None,
    ) -> None:
        with session_scope(self._session_factory) as session:
            session.add(
                ModelCall(
                    run_id=self._run_id,
                    agent=self._agent,
                    provider=self._provider_name,
                    model=model,
                    prompt_hash=prompt_hash,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    seed=seed,
                    cached=False,
                )
            )


__all__ = ["ModelClient", "StructuredOutputError"]
