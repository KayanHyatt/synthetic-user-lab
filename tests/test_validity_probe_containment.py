"""PROJECT_SPEC.md §M6 Deviation 11: the two failures a real recording pass
found (PROJECT_SPEC.md §M6, Deviation 9) -- real structured-output failures
crashing the whole harness because the probe path had no per-run
containment analogous to `sul.runner.orchestrator._run_one_persona`'s
per-run `except BudgetExceeded` / `except (ProviderError,
StructuredOutputError)` boundary.

Two layers are tested separately, deliberately: `sul.validity.acquiescence`/
`.position`'s per-subject containment is exercised directly against
`ScriptedProvider` (a content-aware test double `sul.validity.harness`'s
allow-list refuses to admit -- see `tests/test_validity_harness.py
::test_scripted_provider_is_refused_at_the_harness_boundary`), and
`sul.validity.harness`'s section-level containment and three-way status
resolution is exercised by monkeypatching one probe function at a time,
mirroring `tests/test_validity_harness.py
::test_reproducibility_never_touches_the_harness_level_provider`'s own
pattern.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import RunStatus
from sul.models import Run
from sul.providers.base import Completion, Message, Refused
from sul.providers.fake import FakeProvider
from sul.validity.acquiescence import AcquiescenceResult, run_acquiescence_probe
from sul.validity.harness import run_validity_harness
from sul.validity.position import PositionBiasResult, run_position_bias_probe
from sul.validity.sentinel import MeasurementStatus
from tests.support.scripted_provider import ScriptedProvider, text_completion

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = "configs/panel_validity.yaml"  # 5 personas, seed 1001


_Script = Callable[
    [int, list[Message], str, int | None, type[BaseModel] | None], Completion
]


def _failing_acquiescence_script(fail_at_index: int) -> _Script:
    def _script(
        index: int,
        messages: list[Message],
        model: str,
        seed: int | None,
        response_schema: type[BaseModel] | None,
    ) -> Completion:
        if index == fail_at_index:
            raise Refused("simulated refusal mid-probe")
        prompt = messages[-1].content
        agreement = "disagree" if "unclear about the pricing" in prompt else "agree"
        return text_completion(f'{{"agreement": "{agreement}"}}', model=model)

    return _script


@pytest.mark.asyncio
async def test_acquiescence_probe_drops_a_failed_subject_from_both_sinks_atomically(
    session_factory: sessionmaker[Session],
) -> None:
    """Third subject (0-indexed: calls 4 and 5), negative framing (call 5)
    fails. Its positive-framing reply (call 4, which itself succeeded) must
    not be counted either -- see the module docstring on atomicity.
    """
    result = await run_acquiescence_probe(
        session_factory,
        provider=ScriptedProvider(script=_failing_acquiescence_script(5)),
        provider_name="fake",
        model="fake-1",
        panel_path=PANEL_PATH,
        base_path=REPO_ROOT,
    )

    assert result.subjects_attempted == 5
    assert result.subjects_measured == 4
    assert len(result.failures) == 1
    assert result.failures[0].turn_index == 1

    # Every surviving subject's positive reply was "agree" and negative
    # reply was "disagree" (per the script) -- a rate of exactly 1.0/0.0
    # (not something in between) is only possible if all 4 surviving
    # subjects landed in both sinks, i.e. the sinks are the same length and
    # the failed subject is in neither.
    assert result.positive_agree_rate == 1.0
    assert result.negative_agree_rate == 0.0
    assert result.agreement_gap == 1.0

    with session_factory() as session:
        runs = session.execute(select(Run).order_by(Run.id)).scalars().all()
    assert len(runs) == 5
    failed = [r for r in runs if r.status == RunStatus.FAILED]
    completed = [r for r in runs if r.status == RunStatus.COMPLETED]
    assert len(failed) == 1
    assert failed[0].error is not None and "simulated refusal" in failed[0].error
    assert len(completed) == 4


def _failing_position_script(fail_at_index: int) -> _Script:
    def _script(
        index: int,
        messages: list[Message],
        model: str,
        seed: int | None,
        response_schema: type[BaseModel] | None,
    ) -> Completion:
        if index == fail_at_index:
            raise Refused("simulated refusal mid-probe")
        prompt = messages[-1].content
        match = re.search(r"^1\. (.+)$", prompt, re.MULTILINE)
        assert match is not None, f"no numbered option found in prompt:\n{prompt}"
        first_option = match.group(1).strip()
        assert response_schema is not None
        reply = response_schema(choice=first_option)
        return text_completion(reply.model_dump_json(), model=model)

    return _script


@pytest.mark.asyncio
async def test_position_probe_drops_a_failed_subject_from_both_sinks_atomically(
    session_factory: sessionmaker[Session],
) -> None:
    """Same shape as the acquiescence test above: third subject's reversed-
    order call (index 5) fails; its original-order reply (index 4, which
    succeeded) must not be counted either.
    """
    result = await run_position_bias_probe(
        session_factory,
        provider=ScriptedProvider(script=_failing_position_script(5)),
        provider_name="fake",
        model="fake-1",
        panel_path=PANEL_PATH,
        base_path=REPO_ROOT,
    )

    assert result.subjects_attempted == 5
    assert result.subjects_measured == 4
    assert len(result.failures) == 1
    assert result.failures[0].turn_index == 1

    # The script always picks whichever option is listed first -- content-
    # blind, position-driven. A share of exactly 1.0/0.0 (not in between)
    # is only possible if all 4 surviving subjects landed in both orderings'
    # sinks.
    assert result.first_position_share_original_order == 1.0
    assert result.first_position_share_reversed_order == 0.0
    assert result.preference_shift == 1.0

    with session_factory() as session:
        runs = session.execute(select(Run).order_by(Run.id)).scalars().all()
    assert len(runs) == 5
    failed = [r for r in runs if r.status == RunStatus.FAILED]
    completed = [r for r in runs if r.status == RunStatus.COMPLETED]
    assert len(failed) == 1
    assert failed[0].error is not None and "simulated refusal" in failed[0].error
    assert len(completed) == 4


async def _default_discriminative(*args: object, **kwargs: object) -> object:
    from sul.validity.discriminative import DiscriminativeValidityResult

    return DiscriminativeValidityResult(
        bad_rows=[],
        good_rows=[],
        bad_blocker_confusion_count=6,
        good_blocker_confusion_count=1,
        material_difference=True,
        bad_study_id=0,
        good_study_id=0,
        provenance=[],
        bad_personas_attempted=5,
        bad_personas_completed=5,
        good_personas_attempted=5,
        good_personas_completed=5,
        bad_category_counts={},
        good_category_counts={},
        bad_distinct_anchor_count=0,
        good_distinct_anchor_count=0,
    )


async def _default_acquiescence(*args: object, **kwargs: object) -> AcquiescenceResult:
    return AcquiescenceResult(
        positively_framed_question="q+",
        negatively_framed_question="q-",
        positive_agree_rate=0.6,
        negative_agree_rate=0.4,
        agreement_gap=0.2,
        study_id=0,
        provenance=[],
        subjects_attempted=5,
        subjects_measured=5,
    )


async def _default_position(*args: object, **kwargs: object) -> PositionBiasResult:
    return PositionBiasResult(
        options=("A", "B"),
        first_position_share_original_order=0.6,
        first_position_share_reversed_order=0.4,
        preference_shift=0.2,
        study_id=0,
        provenance=[],
        subjects_attempted=5,
        subjects_measured=5,
    )


def _patch_all_three_checks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    discriminative: object = _default_discriminative,
    acquiescence: object = _default_acquiescence,
    position: object = _default_position,
) -> None:
    """Every harness-level containment test below patches all three
    provider-dispatching checks, not just the one under test -- an
    un-patched check would dispatch for real through `FakeProvider`, and
    `provider_name` here is deliberately *not* `"fake"` (offline must be
    `False` to exercise `MEASURED`/`PARTIALLY_MEASURED`), which has no
    pricing table entry (`configs/pricing.yaml` only prices `("fake", ...)`)
    and would fail on an unrelated `UnknownModelError` before reaching
    anything this test cares about.
    """
    monkeypatch.setattr(
        "sul.validity.harness.run_discriminative_validity", discriminative
    )
    monkeypatch.setattr("sul.validity.harness.run_acquiescence_probe", acquiescence)
    monkeypatch.setattr("sul.validity.harness.run_position_bias_probe", position)


@pytest.mark.asyncio
async def test_harness_resolves_a_partial_section_to_partially_measured(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _partial_acquiescence(
        *args: object, **kwargs: object
    ) -> AcquiescenceResult:
        return AcquiescenceResult(
            positively_framed_question="q+",
            negatively_framed_question="q-",
            positive_agree_rate=1.0,
            negative_agree_rate=0.0,
            agreement_gap=1.0,
            study_id=0,
            provenance=[],
            subjects_attempted=5,
            subjects_measured=4,
        )

    _patch_all_three_checks(monkeypatch, acquiescence=_partial_acquiescence)

    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="not-fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )

    assert report.acquiescence_bias.status == MeasurementStatus.PARTIALLY_MEASURED
    assert report.acquiescence_bias.subjects_attempted == 5
    assert report.acquiescence_bias.subjects_measured == 4
    assert report.acquiescence_bias.reason is not None
    assert "4" in report.acquiescence_bias.reason
    assert "5" in report.acquiescence_bias.reason
    # Partial data is still rendered -- it's real, just over a smaller panel.
    assert report.acquiescence_bias.agreement_gap == 1.0

    # The other sections were not touched by acquiescence's degradation.
    assert report.position_bias.status == MeasurementStatus.MEASURED
    assert report.discriminative_validity.status == MeasurementStatus.MEASURED
    assert report.known_answer_calibration.status == MeasurementStatus.MEASURED


@pytest.mark.asyncio
async def test_harness_never_renders_a_confident_rate_over_zero_survivors(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every subject failing must not resolve to a `0.0` gap that looks like
    a measured, unbiased panel -- PROJECT_SPEC.md §M6 Deviation 11.
    """

    async def _wiped_out_acquiescence(
        *args: object, **kwargs: object
    ) -> AcquiescenceResult:
        return AcquiescenceResult(
            positively_framed_question="q+",
            negatively_framed_question="q-",
            positive_agree_rate=0.0,  # what `agreement_rate([])` returns
            negative_agree_rate=0.0,
            agreement_gap=0.0,
            study_id=0,
            provenance=[],
            subjects_attempted=5,
            subjects_measured=0,
        )

    _patch_all_three_checks(monkeypatch, acquiescence=_wiped_out_acquiescence)

    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="not-fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )

    assert report.acquiescence_bias.status == MeasurementStatus.PARTIALLY_MEASURED
    assert report.acquiescence_bias.subjects_attempted == 5
    assert report.acquiescence_bias.subjects_measured == 0
    # None, not 0.0 -- a reader must never mistake "nobody survived" for "no
    # bias detected."
    assert report.acquiescence_bias.positive_agree_rate is None
    assert report.acquiescence_bias.negative_agree_rate is None
    assert report.acquiescence_bias.agreement_gap is None


@pytest.mark.asyncio
async def test_harness_degrades_a_section_that_fails_outright_while_others_still_render(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _explode(*args: object, **kwargs: object) -> PositionBiasResult:
        raise Refused("simulated total section failure")

    _patch_all_three_checks(monkeypatch, position=_explode)

    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="not-fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )

    assert report.position_bias.status == MeasurementStatus.PARTIALLY_MEASURED
    assert report.position_bias.reason is not None
    assert "section failed" in report.position_bias.reason
    assert report.position_bias.preference_shift is None
    assert report.position_bias.provenance == []

    # The harness completed and every other section still rendered --
    # nothing already dispatched/billed for them was discarded.
    assert report.reproducibility.finding_count_variance == 0.0
    assert report.discriminative_validity.status == MeasurementStatus.MEASURED
    assert report.acquiescence_bias.status == MeasurementStatus.MEASURED
    assert report.known_answer_calibration.status == MeasurementStatus.MEASURED
