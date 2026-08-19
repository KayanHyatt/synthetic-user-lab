"""`ScriptedProvider`: an `LLMProvider` whose response (or exception) on each
call is decided by a caller-supplied function of that call's index and
context. Used where `FakeProvider`'s synthesis can't produce the specific
scenario a test needs -- a mid-session crash, a fixed malformed response, or
an out-of-range evidence reference a `Literal`-constrained schema would
never let `FakeProvider` synthesise in the first place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from sul.providers.base import Completion, LLMProvider, Message, Usage


@dataclass
class ScriptedProvider:
    script: Callable[
        [int, list[Message], str, int | None, type[BaseModel] | None], Completion
    ]
    call_count: int = field(default=0, init=False)

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
        index = self.call_count
        self.call_count += 1
        return self.script(index, messages, model, seed, response_schema)


def text_completion(text: str, *, model: str = "fake-1") -> Completion:
    return Completion(
        text=text,
        usage=Usage(tokens_in=10, tokens_out=5),
        model=model,
        stop_reason="end_turn",
    )


class SimulatedCrash(Exception):
    """A stand-in for the process being killed: a genuinely unexpected
    failure that `sul.runner.orchestrator._run_one_persona` does not catch
    (only `BudgetExceeded` and `StructuredOutputError` are handled per-run),
    so it propagates all the way out of `run_study`, leaving whatever was
    already committed in place.
    """


@dataclass
class CrashAfterNCalls:
    """Wraps a real `LLMProvider` and raises `SimulatedCrash` once the
    `n`-th call is reached -- the offline stand-in for "kill the process at
    50%" (PROJECT_SPEC.md §M4 acceptance): every prior call was dispatched
    and billed normally (through the real inner provider, e.g.
    `FakeProvider`), and the crash is a genuinely unhandled exception, not a
    graceful stop.
    """

    inner: LLMProvider
    n: int
    call_count: int = field(default=0, init=False)

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
        self.call_count += 1
        if self.call_count >= self.n:
            raise SimulatedCrash(f"simulated crash at call {self.call_count}")
        return await self.inner.complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            response_schema=response_schema,
        )


__all__ = ["CrashAfterNCalls", "ScriptedProvider", "SimulatedCrash", "text_completion"]
