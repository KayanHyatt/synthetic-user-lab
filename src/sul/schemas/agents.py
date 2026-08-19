"""Structured-output schemas for the M4 turn loop's three agents.

Every one of these is a `response_schema` passed straight into
`sul.providers.client.ModelClient.complete` -- parsed through M2's
structured-output path (one bounded repair turn, no regex, no fallback
default). None of them is ever hand-parsed elsewhere.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sul.enums import FindingCategory

PersonaState = Literal["proceeding", "confused", "gave_up", "completed"]


class PersonaReply(BaseModel):
    """One persona turn: what the persona says, and a signal of how the task
    is going for them. `state` is what the moderator's probing logic reads --
    "probing only on confusion or abandonment signals" (PROJECT_SPEC.md §M4)
    means "probe when `state` is `confused` or `gave_up`", not a judgement
    call re-derived from the free-text `utterance` by string-matching it.
    """

    model_config = ConfigDict(extra="forbid")

    utterance: str = Field(min_length=1)
    state: PersonaState


class ModeratorFollowup(BaseModel):
    """One adaptive follow-up question, generated only when the persona's
    prior turn signalled confusion or abandonment.
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)


class AnalystFinding(BaseModel):
    """One structured finding, in its stable post-resolution shape --
    `evidence_turn_ordinal` is a plain `int` here because this is what
    `sul.agents.analyst.run_analyst` returns to its caller *after* the
    provider's response has already been validated against the run-specific,
    `Literal`-constrained schema `build_analyst_response_schema` builds. The
    provider is never handed this class directly as a `response_schema` --
    see that function's docstring for why the Literal narrowing has to happen
    on a schema built fresh per run.
    """

    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    severity: int = Field(ge=1, le=5)
    summary: str = Field(min_length=1)
    evidence_turn_ordinal: int


def build_analyst_response_schema(
    valid_evidence_ordinals: tuple[int, ...],
) -> type[BaseModel]:
    """Build a run-specific `AnalystFindings` variant whose
    `evidence_turn_ordinal` field can only validate to one of this run's own
    persona-turn ordinals (`AnalystContext.persona_turn_ordinals()`).

    This is the mechanism, not a convention, behind the §M4 carry-forward's
    "verified against the stored transcript ... rejected loudly on mismatch":
    the Literal type makes an out-of-range reference a schema-validation
    failure, which M2's structured-output path already turns into one repair
    turn and then a loud `StructuredOutputError` -- there is no second,
    separate verification step to forget to call.

    A distinct class is built per run (never shared or cached across runs)
    because the valid ordinal set is itself per-run; `FakeProvider` keys on
    `response_schema.model_json_schema()`, not object identity, so this does
    not defeat cross-run determinism -- two runs with the same ordinal range
    still key identically.
    """
    if not valid_evidence_ordinals:
        raise ValueError(
            "a run with no persona turns has nothing a Finding could cite as "
            "evidence; the Analyst must not be invoked for it"
        )

    class _RunAnalystFinding(BaseModel):
        model_config = ConfigDict(extra="forbid")

        category: FindingCategory
        severity: int = Field(ge=1, le=5)
        summary: str = Field(min_length=1)
        evidence_turn_ordinal: Literal[valid_evidence_ordinals]  # type: ignore[valid-type]

    class _RunAnalystFindings(BaseModel):
        model_config = ConfigDict(extra="forbid")

        findings: list[_RunAnalystFinding] = Field(default_factory=list)

    return _RunAnalystFindings


__all__ = [
    "AnalystFinding",
    "ModeratorFollowup",
    "PersonaReply",
    "PersonaState",
    "build_analyst_response_schema",
]
