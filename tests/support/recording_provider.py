"""`RecordingProvider`: wraps any `LLMProvider` and captures the *exact*
outbound payload of every call -- the seam `sul.providers.client.ModelClient`
dispatches through, which is where the §M4 carry-forward's isolation test has
to look ("test the rendered prompt, not the object graph").

Calls are classified into persona/moderator/analyst by inspecting each
call's system-prompt content for that agent's template's own distinctive
marker text, rather than by a label the test harness attaches itself --
`sul.agents.persona`/`.moderator`/`.analyst` never share a marker string, so
this is exercising the real rendered output, not trusting a side channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from sul.providers.base import Completion, LLMProvider, Message

PERSONA_MARKER = "The product artefact in front of you"
MODERATOR_MARKER = "You are a research moderator running a usability session."
ANALYST_MARKER = "You are a research analyst."


@dataclass(frozen=True)
class CapturedCall:
    messages: list[Message]
    model: str
    temperature: float
    max_tokens: int
    seed: int | None
    response_schema: type[BaseModel] | None

    @property
    def system_text(self) -> str:
        return "\n".join(m.content for m in self.messages if m.role == "system")

    @property
    def full_payload_text(self) -> str:
        """Every byte of the outbound payload: every message's role and
        content, plus the schema's field names and field descriptions if one
        was supplied. This is what a leak-detection assertion must scan --
        not just the system prompt -- since a schema field description is a
        real leak path (§M4 carry-forward).
        """
        parts = [f"{m.role}:{m.content}" for m in self.messages]
        if self.response_schema is not None:
            parts.append(str(self.response_schema.model_json_schema()))
        return "\n".join(parts)

    def is_persona_directed(self) -> bool:
        return PERSONA_MARKER in self.system_text

    def is_moderator_directed(self) -> bool:
        return MODERATOR_MARKER in self.system_text

    def is_analyst_directed(self) -> bool:
        return ANALYST_MARKER in self.system_text


@dataclass
class RecordingProvider:
    """An `LLMProvider` decorator that appends a `CapturedCall` for every
    dispatch before delegating to `inner`. Never used outside tests.
    """

    inner: LLMProvider
    calls: list[CapturedCall] = field(default_factory=list)

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
        self.calls.append(
            CapturedCall(
                messages=list(messages),
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
                response_schema=response_schema,
            )
        )
        return await self.inner.complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            response_schema=response_schema,
        )

    def persona_calls(self) -> list[CapturedCall]:
        return [c for c in self.calls if c.is_persona_directed()]

    def moderator_calls(self) -> list[CapturedCall]:
        return [c for c in self.calls if c.is_moderator_directed()]

    def analyst_calls(self) -> list[CapturedCall]:
        return [c for c in self.calls if c.is_analyst_directed()]


__all__ = [
    "ANALYST_MARKER",
    "MODERATOR_MARKER",
    "PERSONA_MARKER",
    "CapturedCall",
    "RecordingProvider",
]
