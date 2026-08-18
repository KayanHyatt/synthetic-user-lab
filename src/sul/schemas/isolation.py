"""PersonaContext: the persona-isolation boundary, enforced as a type.

This is the only object that may ever be assembled into a persona agent's
input. `build()` reads only the attributes a persona is permitted to see —
`Persona.card_text`, the target `Artefact`'s kind and body, and the content of
prior moderator turns passed in explicitly — and never follows a
relationship. It never touches `persona.panel` (which would raise, see
`sul.models.panel`) and never receives the research goal, sibling personas,
or prior findings as arguments in the first place.

Context isolation is the project's thesis: a persona that can see the
research question answers the research question instead of behaving like a
user. Representing the boundary as a type (rather than trusting prompt
wording) is what M4's isolation test checks against.
"""

from __future__ import annotations

from sul.enums import ArtefactKind, TurnRole
from sul.models.panel import Persona
from sul.models.run import Turn
from sul.models.study import Artefact
from sul.schemas.base import ORMModel


class PersonaContext(ORMModel):
    """Everything a persona agent may see. Nothing else."""

    persona_card: str
    artefact_kind: ArtefactKind
    artefact_body: str
    moderator_turns: list[str]

    @classmethod
    def build(
        cls, *, persona: Persona, artefact: Artefact, turns: list[Turn]
    ) -> PersonaContext:
        """Build a PersonaContext from a persona, the artefact under test, and
        that persona's own prior turns (queried explicitly by the caller, not
        traversed via a relationship).
        """
        moderator_turns = [
            turn.content for turn in turns if turn.role == TurnRole.MODERATOR
        ]
        return cls(
            persona_card=persona.card_text,
            artefact_kind=artefact.kind,
            artefact_body=artefact.body,
            moderator_turns=moderator_turns,
        )
