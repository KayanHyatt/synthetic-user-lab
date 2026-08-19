"""The Analyst agent: reads one completed run's transcript, and nothing else,
and emits `Finding[]` against the fixed taxonomy (PROJECT_SPEC.md §1, §M4).

The only input this module accepts is `sul.schemas.isolation.AnalystContext`
-- `extra="forbid"`, one field (`transcript`), no research goal, no other
run's data, no persona identity. As with `sul.agents.persona`, no ORM model
and no concrete provider adapter is imported here.

Every finding this module returns is verified-by-construction, not by a
separate check afterwards: `evidence_turn_ordinal` is validated against a
schema built fresh per run
(`sul.schemas.agents.build_analyst_response_schema`) whose `Literal` type
only accepts this run's own persona-turn ordinals. An out-of-range reference
is therefore a structured-output validation failure -- handled by M2's
existing one-repair-turn path, and a loud `StructuredOutputError` if the
repair also fails to name a real ordinal.
"""

from __future__ import annotations

import jinja2

from sul.enums import TurnRole
from sul.providers.base import Message
from sul.providers.client import ModelClient
from sul.schemas.agents import AnalystFinding, build_analyst_response_schema
from sul.schemas.isolation import AnalystContext

ANALYST_TEMPLATE_VERSION = "analyst.v1"
_TEMPLATE_FILENAME = f"{ANALYST_TEMPLATE_VERSION}.j2"

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.agents", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)

_ROLE_LABEL: dict[TurnRole, str] = {
    TurnRole.MODERATOR: "moderator",
    TurnRole.PERSONA: "persona",
}


def render_analyst_system_prompt() -> str:
    template = _env.get_template(_TEMPLATE_FILENAME)
    return template.render().strip() + "\n"


def render_transcript(context: AnalystContext) -> str:
    """Render `context.transcript` as ordinal-tagged lines -- not a template
    (there is no instructional text here, only a mechanical rendering of
    structured data the Analyst must quote ordinals from), but still
    byte-stable: `context.transcript` is already ordinal-ordered by
    `AnalystContext.build`.
    """
    lines = [
        f"[{ordinal}] {_ROLE_LABEL[role]}: {content}"
        for ordinal, role, content in context.transcript
    ]
    return "\n".join(lines)


def build_analyst_messages(context: AnalystContext) -> list[Message]:
    return [
        Message(role="system", content=render_analyst_system_prompt()),
        Message(role="user", content=render_transcript(context)),
    ]


async def run_analyst(
    *,
    client: ModelClient,
    context: AnalystContext,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int,
) -> list[AnalystFinding]:
    """Extract findings from one completed run's transcript.

    Returns the stable `AnalystFinding` shape (plain `int`
    `evidence_turn_ordinal`) after the provider's response has already
    validated against this run's own `Literal`-constrained schema -- see the
    module docstring.
    """
    valid_ordinals = context.persona_turn_ordinals()
    response_schema = build_analyst_response_schema(valid_ordinals)
    messages = build_analyst_messages(context)

    raw = await client.complete(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=response_schema,
        template_version=ANALYST_TEMPLATE_VERSION,
    )

    # `response_schema` is a class built fresh per run
    # (`build_analyst_response_schema`), so its static type is the generic
    # `type[BaseModel]` -- `raw` therefore has no statically-known
    # `.findings` attribute even though the real object always has one.
    # `model_dump()` sidesteps that without an `Any`-typed `getattr`/
    # `type: ignore` at every field access below.
    payload = raw.model_dump()
    return [
        AnalystFinding(
            category=item["category"],
            severity=item["severity"],
            summary=item["summary"],
            evidence_turn_ordinal=item["evidence_turn_ordinal"],
        )
        for item in payload["findings"]
    ]


__all__ = [
    "ANALYST_TEMPLATE_VERSION",
    "build_analyst_messages",
    "render_analyst_system_prompt",
    "render_transcript",
    "run_analyst",
]
