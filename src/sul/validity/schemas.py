"""Isolation contexts and structured-output schemas for M6's two new probe
types (PROJECT_SPEC.md §M6.3, §M6.4). Mirrors `sul.schemas.isolation` /
`sul.schemas.agents`'s split: contexts here are what a probe agent may see
(no research goal, no other persona, no cross-run data -- same isolation
rules as `PersonaContext`), schemas here are what it must reply with.

Neither probe reuses `PersonaReply`: acquiescence and position-bias need a
directly comparable structured answer (an enum, a choice among named
options), not free text a metric would have to string-match -- the same
"never regex an LLM response" reasoning that already governs
`sul.schemas.agents`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sul.enums import ArtefactKind

FramingLabel = Literal["positive", "negative"]
Agreement = Literal["agree", "disagree", "unsure"]


class FramingProbeContext(BaseModel):
    """Everything the acquiescence probe may see: a persona card, the
    artefact, and one already-framed question. No research goal, no sibling
    persona, no prior transcript -- each probe call is a fresh, isolated,
    single-turn session, same isolation rule as `PersonaContext`.
    """

    model_config = ConfigDict(extra="forbid")

    persona_card: str
    artefact_kind: ArtefactKind
    artefact_body: str
    framed_question: str


class FramingProbeReply(BaseModel):
    """A structured agree/disagree/unsure signal -- never inferred from free
    text after the fact.
    """

    model_config = ConfigDict(extra="forbid")

    agreement: Agreement


class ChoiceProbeContext(BaseModel):
    """Everything the position-bias probe may see: a persona card, the
    artefact, and a fixed, already-ordered tuple of option labels. The
    caller decides the order (including any shuffling) before building this
    -- the probe itself has no opinion about position.
    """

    model_config = ConfigDict(extra="forbid")

    persona_card: str
    artefact_kind: ArtefactKind
    artefact_body: str
    options: tuple[str, ...] = Field(min_length=2)


def build_choice_probe_schema(option_labels: tuple[str, ...]) -> type[BaseModel]:
    """Build a call-specific `ChoiceProbeReply` whose `choice` field can only
    validate to one of `option_labels` -- the same run-specific-`Literal`
    mechanism `sul.schemas.agents.build_analyst_response_schema` uses, for
    the same reason: an out-of-range choice becomes a schema-validation
    failure (M2's one bounded repair turn, then a loud
    `StructuredOutputError`), not a value a caller has to separately check.
    """
    if len(option_labels) < 2:
        raise ValueError("a choice probe needs at least two options to choose between")

    class _ChoiceProbeReply(BaseModel):
        model_config = ConfigDict(extra="forbid")

        choice: Literal[option_labels]  # type: ignore[valid-type]

    return _ChoiceProbeReply


__all__ = [
    "Agreement",
    "ChoiceProbeContext",
    "FramingLabel",
    "FramingProbeContext",
    "FramingProbeReply",
    "build_choice_probe_schema",
]
