"""PROJECT_SPEC.md §M6.3: ask matched positively- and negatively-framed
versions of the same question, and measure how often the panel simply agrees
with the framing.

**Per-subject containment (§M6 Deviation 11).** Each subject feeds *two*
sinks (`positive_replies`/`negative_replies`), and `agreement_gap` is only
meaningful as a paired comparison across them. A subject that fails partway
through (a transient provider error, or a `StructuredOutputError` that
survived the one bounded repair turn) is therefore discarded from *both*
sinks atomically, never just the framing that failed -- each subject's two
replies are accumulated into local variables first and only extended onto
the shared sinks once both calls for that subject have succeeded. This
mirrors `sul.runner.orchestrator._run_one_persona`'s per-run containment --
`except BudgetExceeded`, then `except (ProviderError, StructuredOutputError)`
(PROJECT_SPEC.md §M4, §M7 carry-forward fix) -- scoped to one subject
instead of one persona's whole turn loop, plus
`call_with_backoff` (`sul.runner.retry`) around each individual probe call
-- neither of which this module had before this deviation; a single
transient `RateLimited` used to kill the whole harness run with no retry at
all.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.providers.base import LLMProvider, ProviderError
from sul.providers.budget import BudgetGuard
from sul.providers.client import ModelClient, StructuredOutputError
from sul.runner.retry import call_with_backoff
from sul.runner.seeds import derive_seed
from sul.validity.data import load_provenance
from sul.validity.model import AgentProvenance
from sul.validity.probes import run_framing_probe
from sul.validity.runs import (
    mark_probe_run_completed,
    mark_probe_run_failed,
    materialize_probe_subjects,
)
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
class ProbeSubjectFailure:
    """One subject dropped from a probe section -- persona identity, which
    framing/ordering turn it failed on, and the error, mirroring what
    `sul.runner.orchestrator.RunOutcome.error` already carries for a failed
    M4 turn-loop run.
    """

    persona_name: str
    turn_index: int
    error: str


@dataclass(frozen=True)
class AcquiescenceResult:
    positively_framed_question: str
    negatively_framed_question: str
    positive_agree_rate: float
    negative_agree_rate: float
    agreement_gap: float
    study_id: int
    provenance: list[AgentProvenance]
    # Defaulted (not just optional) so existing callers that construct this
    # dataclass by keyword without these three -- e.g.
    # tests/test_validity_harness.py's monkeypatched stand-in -- keep working
    # unchanged; every real call site below always sets them explicitly.
    subjects_attempted: int = 0
    subjects_measured: int = 0
    failures: tuple[ProbeSubjectFailure, ...] = ()


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
    max_cost_usd: float | None = None,
) -> AcquiescenceResult:
    """`max_cost_usd`, when given, is a ceiling on *this section's* spend
    alone -- `BudgetGuard` is per-study (`sul.providers.budget`), and this
    function materialises its own study, so it is not a share of some
    whole-harness total. Omitted (the default), probe spend is unbounded, as
    it always was before this parameter existed.
    """
    root = base_path if base_path is not None else Path.cwd()
    materialized = await materialize_probe_subjects(
        session_factory,
        artefact_path=artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.3 acquiescence probe",
    )
    budget = (
        BudgetGuard(session_factory, materialized.study_id, max_cost_usd)
        if max_cost_usd is not None
        else None
    )

    positive_replies: list[Agreement] = []
    negative_replies: list[Agreement] = []
    questions = ((0, positive_question), (1, negative_question))
    failures: list[ProbeSubjectFailure] = []

    for subject in materialized.subjects:
        client = ModelClient(
            provider,
            provider_name,
            session_factory,
            agent=AgentRole.VALIDITY_PROBE,
            budget=budget,
            run_id=subject.run_id,
        )
        subject_replies: list[Agreement] = []
        try:
            for turn_index, question in questions:
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
                # functools.partial, not a bare closure over the loop
                # variables -- ruff's B023 exists for exactly the deferred-
                # call failure mode that guards against, and a lambda with
                # default-argument values (the usual workaround) hits a
                # known mypy inference gap against call_with_backoff's
                # generic `T`. `partial` binds the arguments eagerly, at
                # this point in the loop, same as the default-argument
                # trick would.
                reply = await call_with_backoff(
                    functools.partial(
                        run_framing_probe,
                        client=client,
                        context=context,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        seed=seed,
                    )
                )
                subject_replies.append(reply.agreement)
        except (ProviderError, StructuredOutputError) as exc:
            # Discarded from *both* sinks -- see the module docstring. Only
            # the turn that actually failed is recorded; a subject that
            # fails on turn_index=1 still had a successful turn_index=0
            # call, which is billed and logged, just not counted toward
            # either rate.
            failed_turn_index = questions[len(subject_replies)][0]
            mark_probe_run_failed(session_factory, subject.run_id, str(exc))
            failures.append(
                ProbeSubjectFailure(
                    persona_name=subject.persona_name,
                    turn_index=failed_turn_index,
                    error=str(exc),
                )
            )
            continue

        positive_replies.append(subject_replies[0])
        negative_replies.append(subject_replies[1])
        mark_probe_run_completed(session_factory, subject.run_id)

    positive_rate = agreement_rate(positive_replies)
    negative_rate = agreement_rate(negative_replies)

    with session_factory() as session:
        provenance = load_provenance(session, study_ids=[materialized.study_id])

    return AcquiescenceResult(
        positively_framed_question=positive_question,
        negatively_framed_question=negative_question,
        positive_agree_rate=positive_rate,
        negative_agree_rate=negative_rate,
        agreement_gap=abs(positive_rate - negative_rate),
        study_id=materialized.study_id,
        provenance=provenance,
        subjects_attempted=len(materialized.subjects),
        subjects_measured=len(materialized.subjects) - len(failures),
        failures=tuple(failures),
    )


__all__ = [
    "DEFAULT_ARTEFACT_PATH",
    "DEFAULT_NEGATIVE_QUESTION",
    "DEFAULT_PANEL_PATH",
    "DEFAULT_POSITIVE_QUESTION",
    "AcquiescenceResult",
    "ProbeSubjectFailure",
    "agreement_rate",
    "run_acquiescence_probe",
]
