"""PersonaContext and AnalystContext: the two isolation boundaries, enforced
as types.

These are the only objects that may ever be assembled into a persona agent's
or the Analyst's input. Each `.build()` reads only the attributes that agent
is permitted to see, and never follows an ORM relationship — no `persona.panel`
(which would raise, see `sul.models.panel`), no `study.research_goal` for the
persona side, no cross-run data for the Analyst side.

Context isolation is the project's thesis: a persona that can see the
research question answers the research question instead of behaving like a
user, and an Analyst that sees more than one completed transcript at a time
can no longer attribute a finding to a specific run. Representing each
boundary as a type — `extra="forbid"`, a fixed field set, no research-goal or
cross-persona/cross-run parameter for `.build()` to accept in the first place
— is what M4's isolation tests check against; `lazy="raise"` and code review
are backstops, not the mechanism.
"""

from __future__ import annotations

from pydantic import ConfigDict

from sul.enums import ArtefactKind, TurnRole
from sul.models.panel import Persona
from sul.models.run import Turn
from sul.models.study import Artefact
from sul.schemas.base import ORMModel


class PersonaContext(ORMModel):
    """Everything a persona agent may see. Nothing else.

    `moderator_turns` (M3) is kept as-is for backward compatibility with
    `tests/test_isolation.py`. `transcript` is M4's addition: the persona
    needs its own prior utterances too, to hold a coherent multi-turn
    conversation with itself -- not just the moderator's side of it. Neither
    field can carry a research goal, sibling persona, or finding: both are
    built exclusively from this persona's own `Turn` rows for this run.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    persona_card: str
    artefact_kind: ArtefactKind
    artefact_body: str
    moderator_turns: list[str]
    transcript: list[tuple[TurnRole, str]]

    @classmethod
    def build(
        cls, *, persona: Persona, artefact: Artefact, turns: list[Turn]
    ) -> PersonaContext:
        """Build a PersonaContext from a persona, the artefact under test, and
        that persona's own prior turns (queried explicitly by the caller, not
        traversed via a relationship).
        """
        ordered = sorted(turns, key=lambda t: t.ordinal)
        moderator_turns = [t.content for t in ordered if t.role == TurnRole.MODERATOR]
        transcript = [(t.role, t.content) for t in ordered]
        return cls(
            persona_card=persona.card_text,
            artefact_kind=artefact.kind,
            artefact_body=artefact.body,
            moderator_turns=moderator_turns,
            transcript=transcript,
        )


class AnalystContext(ORMModel):
    """Everything the Analyst may see: one completed run's own transcript,
    ordinal-tagged so a `Finding`'s evidence reference can be resolved back
    to a real `Turn.id` without the Analyst ever handling a database id
    itself. No research goal, no other run's transcript, no persona identity
    or segment -- the spec's "sees only completed transcripts" is read
    literally (PROJECT_SPEC.md §1).
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    transcript: list[tuple[int, TurnRole, str]]

    @classmethod
    def build(cls, *, turns: list[Turn]) -> AnalystContext:
        ordered = sorted(turns, key=lambda t: t.ordinal)
        return cls(transcript=[(t.ordinal, t.role, t.content) for t in ordered])

    def persona_turn_ordinals(self) -> tuple[int, ...]:
        """Ordinals of this run's persona turns -- the only turns a `Finding`
        may cite as evidence (a moderator question is not itself evidence of
        anything the persona experienced).
        """
        return tuple(
            ordinal
            for ordinal, role, _content in self.transcript
            if role == TurnRole.PERSONA
        )


__all__ = ["AnalystContext", "PersonaContext"]
