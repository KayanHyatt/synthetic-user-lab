"""PROJECT_SPEC.md §M6.4: where a scenario presents options, shuffle order
across runs and measure preference shift attributable to position alone.

Two fixed conditions per persona -- `options` in its given order, and
reversed -- rather than a random shuffle per persona: with only two options,
"shuffle" has exactly one non-identity permutation, and running both in a
fixed, named pair (not sampled) is what makes `preference_shift` a comparison
between two known conditions rather than noise from which permutation a given
persona happened to draw.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.providers.base import LLMProvider
from sul.providers.client import ModelClient
from sul.runner.seeds import derive_seed
from sul.validity.data import load_provenance
from sul.validity.model import AgentProvenance
from sul.validity.probes import run_choice_probe
from sul.validity.runs import materialize_probe_subjects
from sul.validity.schemas import ChoiceProbeContext

DEFAULT_ARTEFACT_PATH = "artefacts/bad_onboarding.html"
DEFAULT_PANEL_PATH = "configs/panel_validity.yaml"
DEFAULT_OPTIONS: tuple[str, str] = (
    "Starter plan: $15/mo billed annually, 1 seat",
    "Team plan: $49/mo per workspace, up to 10 seats",
)


def first_option_share(choices: list[str], first_option_label: str) -> float:
    """Share of `choices` that picked `first_option_label` -- computed by
    label, not by position, so it can be compared across the original and
    reversed orderings (where that label sits in a different position).
    """
    if not choices:
        return 0.0
    return sum(1 for c in choices if c == first_option_label) / len(choices)


@dataclass(frozen=True)
class PositionBiasResult:
    options: tuple[str, str]
    first_position_share_original_order: float
    first_position_share_reversed_order: float
    preference_shift: float
    study_id: int
    provenance: list[AgentProvenance]


async def run_position_bias_probe(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    artefact_path: str = DEFAULT_ARTEFACT_PATH,
    panel_path: str = DEFAULT_PANEL_PATH,
    options: tuple[str, str] = DEFAULT_OPTIONS,
    temperature: float = 0.7,
    max_tokens: int = 200,
    base_path: Path | None = None,
) -> PositionBiasResult:
    root = base_path if base_path is not None else Path.cwd()
    materialized = await materialize_probe_subjects(
        session_factory,
        artefact_path=artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.4 position-bias probe",
    )

    first_label = options[0]
    orderings = (
        (0, options),
        (1, (options[1], options[0])),
    )
    choices_by_ordering: dict[int, list[str]] = {0: [], 1: []}

    for subject in materialized.subjects:
        client = ModelClient(
            provider,
            provider_name,
            session_factory,
            agent=AgentRole.VALIDITY_PROBE,
            run_id=subject.run_id,
        )
        for turn_index, ordered_options in orderings:
            context = ChoiceProbeContext(
                persona_card=subject.card_text,
                artefact_kind=materialized.artefact_kind,
                artefact_body=materialized.artefact_body,
                options=ordered_options,
            )
            seed = derive_seed(
                panel_seed=materialized.panel_seed,
                persona_key=subject.persona_name,
                agent=AgentRole.VALIDITY_PROBE,
                turn_index=turn_index,
            )
            choice = await run_choice_probe(
                client=client,
                context=context,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
            choices_by_ordering[turn_index].append(choice)

    share_original = first_option_share(choices_by_ordering[0], first_label)
    share_reversed = first_option_share(choices_by_ordering[1], first_label)

    with session_factory() as session:
        provenance = load_provenance(session, study_ids=[materialized.study_id])

    return PositionBiasResult(
        options=options,
        first_position_share_original_order=share_original,
        first_position_share_reversed_order=share_reversed,
        preference_shift=abs(share_original - share_reversed),
        study_id=materialized.study_id,
        provenance=provenance,
    )


__all__ = [
    "DEFAULT_ARTEFACT_PATH",
    "DEFAULT_OPTIONS",
    "DEFAULT_PANEL_PATH",
    "PositionBiasResult",
    "first_option_share",
    "run_position_bias_probe",
]
