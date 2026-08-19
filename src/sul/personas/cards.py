"""Renders a `SampledPersona` into the natural-language persona card that is
that persona's system prompt (spec §M3: "renders each into a natural-language
persona card used as the persona agent's system prompt").

The template lives in a file, not a string literal (`templates/
persona_card.v1.j2`), and `CARD_TEMPLATE_VERSION` names which version this
build renders with — M4 records it alongside every persona `ModelCall` so a
transcript can always say what template produced its system prompt.

`render_card`'s entire input is a `SampledPersona`: no ORM `Persona`, `Panel`,
or `Study`, and no goal/topic/brief/framing parameter — there is no such
parameter to pass one through. `SampledPersona` (`sul.personas.sampler`)
cannot express a research goal or another persona in the first place, so
nothing this function is handed can leak one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import jinja2

if TYPE_CHECKING:
    from sul.personas.sampler import SampledPersona

CARD_TEMPLATE_VERSION = "persona_card.v1"
_TEMPLATE_FILENAME = f"{CARD_TEMPLATE_VERSION}.j2"

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.personas", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def _humanize(segment: str) -> str:
    return segment.replace("_", " ")


def _format_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def render_card(persona: SampledPersona) -> str:
    """Render `persona`'s card: its name, segment, and its own attributes only."""
    template = _env.get_template(_TEMPLATE_FILENAME)
    attributes = {k: _format_value(v) for k, v in persona.attributes.items()}
    text = template.render(
        name=persona.name, segment=_humanize(persona.segment), attributes=attributes
    )
    return text.strip() + "\n"


__all__ = ["CARD_TEMPLATE_VERSION", "render_card"]
