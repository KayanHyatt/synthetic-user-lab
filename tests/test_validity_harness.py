"""PROJECT_SPEC.md §M6 top-level assembly. The one thing this test exists to
prove: running the full harness against `FakeProvider` ("fake", the only
provider `sul validate` ever constructs) must produce a `ValidityReportModel`
where every content-dependent section is `NOT_MEASURED_OFFLINE` -- never a
number that could be mistaken for a real signal (Correction/Confirm 1 in the
M6 design conversation). Reproducibility is the one exception: always
`measured`, with its structural-zero caveat always present.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.providers.base import Completion, Message
from sul.providers.fake import FakeProvider
from sul.validity.acquiescence import AcquiescenceResult
from sul.validity.discriminative import DiscriminativeValidityResult
from sul.validity.harness import run_validity_harness
from sul.validity.position import PositionBiasResult
from sul.validity.sentinel import MeasurementStatus

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_fake_provider_runs_end_to_end_offline_with_every_content_check_gated(
    session_factory: sessionmaker[Session],
) -> None:
    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )

    assert report.reproducibility.finding_count_variance == 0.0
    assert "structurally guaranteed" in report.reproducibility.caveat

    for section in (
        report.discriminative_validity,
        report.acquiescence_bias,
        report.position_bias,
        report.known_answer_calibration,
    ):
        assert section.status == MeasurementStatus.NOT_MEASURED_OFFLINE
        assert section.reason is not None and "FakeProvider" in section.reason

    assert report.discriminative_validity.material_difference is None
    assert report.discriminative_validity.bad_blocker_confusion_count is None
    assert report.acquiescence_bias.agreement_gap is None
    assert report.position_bias.preference_shift is None
    assert report.known_answer_calibration.detection_rate is None
    assert report.known_answer_calibration.total_defects == 3

    assert report.clustering_margin.margin > 0
    assert report.zero_vector_conflation.total_singleton_clusters >= 2
    assert len(report.threshold_scaling.points) > 0


class _ExplodingProvider:
    """Raises on any dispatch -- proves `measure_reproducibility` never
    touches the harness-level `provider`, only its own internal
    `FakeProvider()` (see `sul.validity.harness`'s module docstring on the
    M6.1/cassette collision: a cassette cannot carry same-seed-repeat
    variance even in principle, so reproducibility always runs against
    FakeProvider, unconditionally).
    """

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: object = None,
    ) -> Completion:
        raise AssertionError(
            "measure_reproducibility must never dispatch through the "
            "harness-level provider"
        )


@pytest.mark.asyncio
async def test_reproducibility_never_touches_the_harness_level_provider(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other four checks *do* use the harness-level provider, so they're
    monkeypatched out here with instant stand-ins -- what's left exercising
    real behaviour is `measure_reproducibility` alone, dispatched against
    `_ExplodingProvider`. If it ever reached that provider, the test would
    raise instead of reaching the final assertion.
    """

    async def _fake_discriminative(
        *args: object, **kwargs: object
    ) -> DiscriminativeValidityResult:
        return DiscriminativeValidityResult(
            bad_rows=[],
            good_rows=[],
            bad_blocker_confusion_count=0,
            good_blocker_confusion_count=0,
            material_difference=False,
        )

    async def _fake_acquiescence(*args: object, **kwargs: object) -> AcquiescenceResult:
        return AcquiescenceResult(
            positively_framed_question="q+",
            negatively_framed_question="q-",
            positive_agree_rate=0.0,
            negative_agree_rate=0.0,
            agreement_gap=0.0,
        )

    async def _fake_position(*args: object, **kwargs: object) -> PositionBiasResult:
        return PositionBiasResult(
            options=("A", "B"),
            first_position_share_original_order=0.0,
            first_position_share_reversed_order=0.0,
            preference_shift=0.0,
        )

    monkeypatch.setattr(
        "sul.validity.harness.run_discriminative_validity", _fake_discriminative
    )
    monkeypatch.setattr(
        "sul.validity.harness.run_acquiescence_probe", _fake_acquiescence
    )
    monkeypatch.setattr("sul.validity.harness.run_position_bias_probe", _fake_position)

    report = await run_validity_harness(
        session_factory,
        provider=_ExplodingProvider(),
        provider_name="definitely-not-fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )

    assert report.reproducibility.finding_count_variance == 0.0
    assert report.reproducibility.mean_top5_cluster_jaccard == 1.0


def test_a_real_provider_name_is_never_gated_to_not_measured_offline() -> None:
    """`sul.validity.harness._is_offline_provider` must only gate `"fake"` --
    a cassette-backed real adapter (any other provider name) stays
    `MEASURED`. This is a unit test of the gate itself, independent of
    actually running a cassette-backed study.
    """
    from sul.validity.harness import _is_offline_provider

    assert _is_offline_provider("fake") is True
    assert _is_offline_provider("anthropic") is False
    assert _is_offline_provider("openai") is False
