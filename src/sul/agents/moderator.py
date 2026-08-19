"""The moderator agent: opens with the scenario task, and asks up to *k*
adaptive follow-ups, probing only on confusion/abandonment signals
(PROJECT_SPEC.md §M4).

Unlike the persona side, the moderator is deliberately not isolation-fenced
by a dedicated context type: it is the one agent that *does* know the
research goal (PROJECT_SPEC.md §1: "Moderator -- knows the research goal,
asks the persona questions, probes"), and PROJECT_SPEC.md's own carry-forward
names it "a documented, deliberate goal-laundering channel". What this module
still must not do -- and does not do, by construction -- is carry state
*across* personas: every function here is pure, taking one run's own
`research_goal` / `scenario_task` / `candidate_questions` / `transcript` as
plain arguments and returning a result, with nothing cached, memoised, or
held on a module-level or class-level object between calls. The caller (the
per-run turn loop in `sul.runner.orchestrator`) constructs these arguments
fresh from that run's own persisted `Turn` rows on every call, so there is no
object here that could outlive -- or leak into -- a different persona's
session; see PROJECT_SPEC.md §M4 carry-forward, "moderator adaptivity is the
cross-persona leak".

No ORM model and no concrete provider adapter is imported here, for the same
reasons as `sul.agents.persona`.
"""

from __future__ import annotations

from typing import Literal

import jinja2

from sul.enums import TurnRole
from sul.providers.base import Message
from sul.providers.client import ModelClient
from sul.schemas.agents import ModeratorFollowup

MODERATOR_FOLLOWUP_TEMPLATE_VERSION = "moderator_followup.v1"
_TEMPLATE_FILENAME = f"{MODERATOR_FOLLOWUP_TEMPLATE_VERSION}.j2"

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.agents", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)

# From the moderator's point of view, its own prior questions are "the
# assistant" and the persona's replies are "the user" it is listening to --
# the mirror image of `sul.agents.persona`'s mapping.
_ROLE_TO_MESSAGE_ROLE: dict[TurnRole, Literal["user", "assistant"]] = {
    TurnRole.MODERATOR: "assistant",
    TurnRole.PERSONA: "user",
}


def render_moderator_system_prompt(
    *, research_goal: str, scenario_task: str, candidate_questions: list[str]
) -> str:
    template = _env.get_template(_TEMPLATE_FILENAME)
    text = template.render(
        research_goal=research_goal,
        scenario_task=scenario_task,
        candidate_questions=candidate_questions,
    )
    return text.strip() + "\n"


def build_moderator_followup_messages(
    *,
    research_goal: str,
    scenario_task: str,
    candidate_questions: list[str],
    transcript: list[tuple[TurnRole, str]],
) -> list[Message]:
    """The exact message list one moderator follow-up call sends: the system
    prompt (which does carry the raw research goal -- this is the documented
    laundering channel) plus this run's transcript so far. `transcript` is
    passed in explicitly by the caller on every call; nothing here retains it
    afterwards.
    """
    system = render_moderator_system_prompt(
        research_goal=research_goal,
        scenario_task=scenario_task,
        candidate_questions=candidate_questions,
    )
    messages = [Message(role="system", content=system)]
    for role, content in transcript:
        messages.append(Message(role=_ROLE_TO_MESSAGE_ROLE[role], content=content))
    return messages


async def run_moderator_followup(
    *,
    client: ModelClient,
    research_goal: str,
    scenario_task: str,
    candidate_questions: list[str],
    transcript: list[tuple[TurnRole, str]],
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int,
) -> ModeratorFollowup:
    """Generate one adaptive follow-up question. The caller decides *whether*
    to call this at all (only on a confusion/abandonment signal, and only
    while under the per-run follow-up cap `k`) -- this function always
    generates exactly one question when called.
    """
    messages = build_moderator_followup_messages(
        research_goal=research_goal,
        scenario_task=scenario_task,
        candidate_questions=candidate_questions,
        transcript=transcript,
    )
    return await client.complete(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        response_schema=ModeratorFollowup,
        template_version=MODERATOR_FOLLOWUP_TEMPLATE_VERSION,
    )


__all__ = [
    "MODERATOR_FOLLOWUP_TEMPLATE_VERSION",
    "build_moderator_followup_messages",
    "render_moderator_system_prompt",
    "run_moderator_followup",
]
