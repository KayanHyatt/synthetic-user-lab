"""PROJECT_SPEC.md §M6.3: ask matched positively- and negatively-framed
versions of the same question, and measure how often the panel simply agrees
with the framing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.providers.base import LLMProvider
from sul.providers.client import ModelClient
from sul.runner.seeds import derive_seed
from sul.validity.probes import run_framing_probe
from sul.validity.runs import materialize_probe_subjects
from sul.validity.schemas import Agreement, FramingProbeContext

DEFAULT_ARTEFACT_PATH = "artefacts/bad_onboarding.html"
DEFAULT_PANEL_PATH = "configs/panel_validity.yaml"
DEFAULT_POSITIVE_QUESTION = "Was the pricing clear?"
DEFAULT_NEGATIVE_QUESTION = "Was anything unclear about the pricing?"


def agreement_rate(replies: list[Agreement]) -> float:
    """Share of `agree` replies among all replies (`agree`/`disagree`/`unsure`)."""
    if not replies:
        return 0.0
    return sum(1 for r in replies if r == "agree") / len(replies)


@dataclass(frozen=True)
class AcquiescenceResult:
    positively_framed_question: str
    negatively_framed_question: str
    positive_agree_rate: float
    negative_agree_rate: float
    agreement_gap: float


async def run_acquiescence_probe(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    artefact_path: str = DEFAULT_ARTEFACT_PATH,
    panel_path: str = DEFAULT_PANEL_PATH,
    positive_question: str = DEFAULT_POSITIVE_QUESTION,
    negative_question: str = DEFAULT_NEGATIVE_QUESTION,
    temperature: float = 0.7,
    max_tokens: int = 200,
    base_path: Path | None = None,
) -> AcquiescenceResult:
    root = base_path if base_path is not None else Path.cwd()
    materialized = await materialize_probe_subjects(
        session_factory,
        artefact_path=artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.3 acquiescence probe",
    )

    positive_replies: list[Agreement] = []
    negative_replies: list[Agreement] = []
    framings = (
        (0, positive_question, positive_replies),
        (1, negative_question, negative_replies),
    )

    for subject in materialized.subjects:
        client = ModelClient(
            provider,
            provider_name,
            session_factory,
            agent=AgentRole.VALIDITY_PROBE,
            run_id=subject.run_id,
        )
        for turn_index, question, sink in framings:
            context = FramingProbeContext(
                persona_card=subject.card_text,
                artefact_kind=materialized.artefact_kind,
                artefact_body=materialized.artefact_body,
                framed_question=question,
            )
            seed = derive_seed(
                panel_seed=materialized.panel_seed,
                persona_key=subject.persona_name,
                agent=AgentRole.VALIDITY_PROBE,
                turn_index=turn_index,
            )
            reply = await run_framing_probe(
                client=client,
                context=context,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
            sink.append(reply.agreement)

    positive_rate = agreement_rate(positive_replies)
    negative_rate = agreement_rate(negative_replies)
    return AcquiescenceResult(
        positively_framed_question=positive_question,
        negatively_framed_question=negative_question,
        positive_agree_rate=positive_rate,
        negative_agree_rate=negative_rate,
        agreement_gap=abs(positive_rate - negative_rate),
    )


__all__ = [
    "DEFAULT_ARTEFACT_PATH",
    "DEFAULT_NEGATIVE_QUESTION",
    "DEFAULT_PANEL_PATH",
    "DEFAULT_POSITIVE_QUESTION",
    "AcquiescenceResult",
    "agreement_rate",
    "run_acquiescence_probe",
]
