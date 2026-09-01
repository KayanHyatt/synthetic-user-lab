"""PROJECT_SPEC.md §M6.2: run the panel on `good_onboarding.html` and
`bad_onboarding.html`; the bad artefact must produce materially more
`blocker`/`confusion` findings.

This module's public function always actually runs both studies and computes
real numbers, regardless of which provider it's given -- there is no
FakeProvider-specific branch here (per the M6 design conversation, Confirm 1:
"no branch that only exists for the fake"). Whether those numbers are worth
showing a reader is a judgement `sul.validity.harness` makes once, centrally,
based on `provider_name` -- not something this module decides about itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.analysis.clustering import FindingRow
from sul.enums import AgentRole, FindingCategory
from sul.providers.base import LLMProvider
from sul.validity.data import load_provenance
from sul.validity.model import AgentProvenance
from sul.validity.runs import run_artefact_study

DEFAULT_BAD_ARTEFACT_PATH = "artefacts/bad_onboarding.html"
DEFAULT_GOOD_ARTEFACT_PATH = "artefacts/good_onboarding.html"
DEFAULT_PANEL_PATH = "configs/panel_validity.yaml"

_DISCRIMINATIVE_CATEGORIES = (FindingCategory.BLOCKER, FindingCategory.CONFUSION)


def blocker_confusion_count(rows: list[FindingRow]) -> int:
    return sum(1 for r in rows if r.category in _DISCRIMINATIVE_CATEGORIES)


def category_counts(rows: list[FindingRow]) -> dict[str, int]:
    """What `blocker_confusion_count` sums (PROJECT_SPEC.md §M6 Deviation
    20): the sum is defensible as the headline "does the panel separate a
    bad artefact from a good one" metric and stays exactly as computed --
    this is disclosure of what's inside it, not a redefinition. Two Analyst
    models can produce the same sum from a different mix (a `blocker`
    reclassified as `confusion` moves an item between buckets and leaves
    the total unchanged), which the sum alone cannot reveal.
    """
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.category.value] = counts.get(row.category.value, 0) + 1
    return dict(sorted(counts.items()))


def distinct_anchor_count(rows: list[FindingRow]) -> int:
    """How many distinct (turn ordinal, category) positions this artefact's
    findings are anchored to, collapsed across personas (PROJECT_SPEC.md §M6
    Deviation 20) -- two personas each reporting `(1, confusion)` is one
    anchor position, not two; the point is coverage of the transcript, not
    a second finding count. A smaller number alongside an unchanged sum
    means fewer distinct places in the conversation are doing the work.
    """
    return len({(row.evidence_turn_ordinal, row.category.value) for row in rows})


def is_material_difference(bad_count: int, good_count: int) -> bool:
    """The threshold rule §M6.2 leaves unspecified: the bad artefact's
    blocker/confusion count must be at least 1.5x the good artefact's *and*
    at least 2 findings more in absolute terms -- the ratio alone would call
    a 1-vs-0 count "material", which is noise, not signal, at this panel
    size.
    """
    return bad_count >= good_count * 1.5 and (bad_count - good_count) >= 2


@dataclass(frozen=True)
class DiscriminativeValidityResult:
    bad_rows: list[FindingRow]
    good_rows: list[FindingRow]
    bad_blocker_confusion_count: int
    good_blocker_confusion_count: int
    material_difference: bool
    bad_study_id: int
    good_study_id: int
    provenance: list[AgentProvenance]
    bad_personas_attempted: int
    bad_personas_completed: int
    good_personas_attempted: int
    good_personas_completed: int
    bad_category_counts: dict[str, int]
    good_category_counts: dict[str, int]
    bad_distinct_anchor_count: int
    good_distinct_anchor_count: int


async def run_discriminative_validity(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    model_by_agent: dict[AgentRole, str] | None = None,
    bad_artefact_path: str = DEFAULT_BAD_ARTEFACT_PATH,
    good_artefact_path: str = DEFAULT_GOOD_ARTEFACT_PATH,
    panel_path: str = DEFAULT_PANEL_PATH,
    base_path: Path | None = None,
    max_cost_usd: float | None = None,
) -> DiscriminativeValidityResult:
    """`max_cost_usd`, when given, is passed to each of the two
    `run_artefact_study` calls below independently -- see that function's
    docstring: the bad-artefact and good-artefact studies get two separate
    ceilings, not one shared across both.
    """
    root = base_path if base_path is not None else Path.cwd()

    bad_run = await run_artefact_study(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        model_by_agent=model_by_agent,
        artefact_path=bad_artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.2 discriminative validity: bad artefact",
        max_cost_usd=max_cost_usd,
    )
    good_run = await run_artefact_study(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        model_by_agent=model_by_agent,
        artefact_path=good_artefact_path,
        panel_path=panel_path,
        base_path=root,
        study_name="M6.2 discriminative validity: good artefact",
        max_cost_usd=max_cost_usd,
    )

    bad_count = blocker_confusion_count(bad_run.rows)
    good_count = blocker_confusion_count(good_run.rows)

    with session_factory() as session:
        provenance = load_provenance(
            session, study_ids=[bad_run.study_id, good_run.study_id]
        )

    return DiscriminativeValidityResult(
        bad_rows=bad_run.rows,
        good_rows=good_run.rows,
        bad_blocker_confusion_count=bad_count,
        good_blocker_confusion_count=good_count,
        material_difference=is_material_difference(bad_count, good_count),
        bad_study_id=bad_run.study_id,
        good_study_id=good_run.study_id,
        provenance=provenance,
        bad_personas_attempted=bad_run.personas_attempted,
        bad_personas_completed=bad_run.personas_completed,
        good_personas_attempted=good_run.personas_attempted,
        good_personas_completed=good_run.personas_completed,
        bad_category_counts=category_counts(bad_run.rows),
        good_category_counts=category_counts(good_run.rows),
        bad_distinct_anchor_count=distinct_anchor_count(bad_run.rows),
        good_distinct_anchor_count=distinct_anchor_count(good_run.rows),
    )


__all__ = [
    "DEFAULT_BAD_ARTEFACT_PATH",
    "DEFAULT_GOOD_ARTEFACT_PATH",
    "DEFAULT_PANEL_PATH",
    "DiscriminativeValidityResult",
    "blocker_confusion_count",
    "category_counts",
    "distinct_anchor_count",
    "is_material_difference",
    "run_discriminative_validity",
]
