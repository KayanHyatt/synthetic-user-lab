"""The persona agent: the one place a persona-bound prompt is assembled.

The only input this module ever accepts is `sul.schemas.isolation
.PersonaContext` -- `extra="forbid"`, a fixed field set, no
goal/topic/brief/framing parameter for it to carry one through. No ORM model
is imported here (an ORM `Persona`/`Panel`/`Study` object never crosses into
this module, even read-only -- PROJECT_SPEC.md §M4 carry-forward), and no
concrete provider adapter is either: `sul.providers.client.ModelClient` is
always injected by the caller.
"""

from __future__ import annotations

from typing import Literal

import jinja2

from sul.enums import TurnRole
from sul.providers.base import Message
from sul.providers.client import ModelClient
from sul.schemas.agents import PersonaReply
from sul.schemas.isolation import PersonaContext

PERSONA_SYSTEM_TEMPLATE_VERSION = "persona_system.v1"
_TEMPLATE_FILENAME = f"{PERSONA_SYSTEM_TEMPLATE_VERSION}.j2"

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.agents", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)

# From the persona's point of view, the moderator is "the user" it is
# talking to and its own prior replies are "the assistant" -- the ordinary
# chat-turn convention, not a research-role label.
_ROLE_TO_MESSAGE_ROLE: dict[TurnRole, Literal["user", "assistant"]] = {
    TurnRole.MODERATOR: "user",
    TurnRole.PERSONA: "assistant",
}


def render_persona_system_prompt(context: PersonaContext) -> str:
    """Render the persona's system prompt from `context` and nothing else."""
    template = _env.get_template(_TEMPLATE_FILENAME)
    text = template.render(
        persona_card=context.persona_card,
        artefact_kind=context.artefact_kind.value,
        artefact_body=context.artefact_body,
    )
    return text.strip() + "\n"


def build_persona_messages(context: PersonaContext) -> list[Message]:
    """The exact message list one persona turn sends: the system prompt, then
    this persona's own transcript so far (`context.transcript`, not
    `context.moderator_turns` -- the latter would drop the persona's own
    prior replies and break multi-turn coherence). Byte-stable: built only
    from `context`'s own fields, in the ordinal order `PersonaContext.build`
    already sorted them into -- no timestamp, id, or non-deterministic order
    enters here.
    """
    messages = [Message(role="system", content=render_persona_system_prompt(context))]
    for role, content in context.transcript:
        messages.append(Message(role=_ROLE_TO_MESSAGE_ROLE[role], content=content))
    return messages


async def run_persona_turn(
    *,
    client: ModelClient,
    context: PersonaContext,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int,
) -> PersonaReply:
    """One persona turn: build the isolated prompt, dispatch it through
    `client`, and return the parsed structured reply. No
    `try`/`except ValidationError`, no regex, no default construction on
    failure -- a malformed reply propagates as
    `sul.providers.client.StructuredOutputError` after M2's one bounded
    repair turn, and the caller (the turn loop) decides what that means for
    the `Run`.
    """
    messages = build_persona_messages(context)
    return await client.complete(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=PersonaReply,
        template_version=PERSONA_SYSTEM_TEMPLATE_VERSION,
    )


__all__ = [
    "PERSONA_SYSTEM_TEMPLATE_VERSION",
    "build_persona_messages",
    "render_persona_system_prompt",
    "run_persona_turn",
]
