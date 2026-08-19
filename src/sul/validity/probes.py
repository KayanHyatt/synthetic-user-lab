"""Two new single-turn probe agents (PROJECT_SPEC.md §M6.3, §M6.4): built
because nothing in M4's turn loop can ask a persona a specific,
experimenter-chosen question and get back a directly comparable structured
answer -- the moderator's follow-up is LLM-chosen and gated on a
confusion/abandonment signal, and `PersonaReply.utterance` is free text with
no agree/disagree or choice-among-options field. Each probe is one isolated
call: persona card + artefact + one fixed prompt, no transcript, no research
goal, no sibling persona -- built and dispatched exactly like
`sul.agents.persona`/`moderator`/`analyst` (`ModelClient` injected, one
`.v1.j2` template, one `template_version` recorded with the call), just
outside the M4 turn loop, since `run_study` never calls these.
"""

from __future__ import annotations

import jinja2

from sul.providers.base import Message
from sul.providers.client import ModelClient
from sul.validity.schemas import (
    ChoiceProbeContext,
    FramingProbeContext,
    FramingProbeReply,
    build_choice_probe_schema,
)

FRAMING_PROBE_TEMPLATE_VERSION = "framing_probe.v1"
CHOICE_PROBE_TEMPLATE_VERSION = "choice_probe.v1"

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.validity", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def render_framing_probe_prompt(context: FramingProbeContext) -> str:
    template = _env.get_template(f"{FRAMING_PROBE_TEMPLATE_VERSION}.j2")
    text = template.render(
        persona_card=context.persona_card,
        artefact_kind=context.artefact_kind.value,
        artefact_body=context.artefact_body,
        framed_question=context.framed_question,
    )
    return text.strip() + "\n"


def build_framing_probe_messages(context: FramingProbeContext) -> list[Message]:
    return [Message(role="user", content=render_framing_probe_prompt(context))]


async def run_framing_probe(
    *,
    client: ModelClient,
    context: FramingProbeContext,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int,
) -> FramingProbeReply:
    messages = build_framing_probe_messages(context)
    return await client.complete(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=FramingProbeReply,
        template_version=FRAMING_PROBE_TEMPLATE_VERSION,
    )


def render_choice_probe_prompt(context: ChoiceProbeContext) -> str:
    template = _env.get_template(f"{CHOICE_PROBE_TEMPLATE_VERSION}.j2")
    text = template.render(
        persona_card=context.persona_card,
        artefact_kind=context.artefact_kind.value,
        artefact_body=context.artefact_body,
        options=context.options,
    )
    return text.strip() + "\n"


def build_choice_probe_messages(context: ChoiceProbeContext) -> list[Message]:
    return [Message(role="user", content=render_choice_probe_prompt(context))]


async def run_choice_probe(
    *,
    client: ModelClient,
    context: ChoiceProbeContext,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int,
) -> str:
    """Run one position-bias probe call. Returns the chosen option's label
    (a plain `str`, already validated to be one of `context.options` by the
    run-specific `Literal` schema `build_choice_probe_schema` builds).
    """
    schema = build_choice_probe_schema(context.options)
    messages = build_choice_probe_messages(context)
    raw = await client.complete(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=schema,
        template_version=CHOICE_PROBE_TEMPLATE_VERSION,
    )
    choice = raw.model_dump()["choice"]
    return str(choice)


__all__ = [
    "CHOICE_PROBE_TEMPLATE_VERSION",
    "FRAMING_PROBE_TEMPLATE_VERSION",
    "build_choice_probe_messages",
    "build_framing_probe_messages",
    "render_choice_probe_prompt",
    "render_framing_probe_prompt",
    "run_choice_probe",
    "run_framing_probe",
]
