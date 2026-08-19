"""PROJECT_SPEC.md §M6 top-level entrypoint. `run_validity_harness` runs all
five checks plus the three `docs/limitations.md` measurements against one
provider, and assembles the single `ValidityReportModel` both
`sul.validity.markdown` and `sul.validity.limitations` render from.

Every content-dependent check (§M6.2-.5) is always actually run, regardless
of provider -- no metric module branches on which provider it was given
(Confirm 1 in the M6 design conversation: "no branch that only exists for the
fake"). Exactly one place decides whether the resulting numbers are worth
showing a reader: `_is_offline_provider` below, checked once, centrally, here.
`"fake"` is the only name that gates a section to `NOT_MEASURED_OFFLINE`; any
other `provider_name` (a cassette-backed real adapter included) is treated as
`MEASURED`, since replaying a cassette is offline but not content-blind.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.providers.base import LLMProvider
from sul.validity.acquiescence import run_acquiescence_probe
from sul.validity.calibration import measure_known_answer_calibration
from sul.validity.discriminative import run_discriminative_validity
from sul.validity.measurements import (
    measure_clustering_margin,
    measure_threshold_scaling,
    measure_zero_vector_conflation,
)
from sul.validity.model import (
    AcquiescenceSection,
    DiscriminativeValiditySection,
    KnownAnswerCalibrationSection,
    PositionBiasSection,
    ValidityReportModel,
)
from sul.validity.position import run_position_bias_probe
from sul.validity.reproducibility import measure_reproducibility
from sul.validity.sentinel import NOT_MEASURED_OFFLINE_REASON, MeasurementStatus

_OFFLINE_PROVIDER_NAMES = frozenset({"fake"})


def _is_offline_provider(provider_name: str) -> bool:
    return provider_name in _OFFLINE_PROVIDER_NAMES


async def run_validity_harness(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    base_path: Path | None = None,
) -> ValidityReportModel:
    root = base_path if base_path is not None else Path.cwd()
    offline = _is_offline_provider(provider_name)

    reproducibility = await measure_reproducibility(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        base_path=root,
    )

    discriminative_result = await run_discriminative_validity(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        base_path=root,
    )
    discriminative_validity = (
        DiscriminativeValiditySection(
            status=MeasurementStatus.NOT_MEASURED_OFFLINE,
            reason=NOT_MEASURED_OFFLINE_REASON,
        )
        if offline
        else DiscriminativeValiditySection(
            status=MeasurementStatus.MEASURED,
            bad_blocker_confusion_count=discriminative_result.bad_blocker_confusion_count,
            good_blocker_confusion_count=discriminative_result.good_blocker_confusion_count,
            material_difference=discriminative_result.material_difference,
        )
    )

    calibration_result = measure_known_answer_calibration(
        discriminative_result.bad_rows
    )
    known_answer_calibration = (
        KnownAnswerCalibrationSection(
            status=MeasurementStatus.NOT_MEASURED_OFFLINE,
            reason=NOT_MEASURED_OFFLINE_REASON,
            total_defects=calibration_result.total_defects,
        )
        if offline
        else KnownAnswerCalibrationSection(
            status=MeasurementStatus.MEASURED,
            total_defects=calibration_result.total_defects,
            detected_count=calibration_result.detected_count,
            detection_rate=calibration_result.detection_rate,
            per_defect=calibration_result.per_defect,
        )
    )

    acquiescence_result = await run_acquiescence_probe(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        base_path=root,
    )
    acquiescence_bias = (
        AcquiescenceSection(
            status=MeasurementStatus.NOT_MEASURED_OFFLINE,
            reason=NOT_MEASURED_OFFLINE_REASON,
        )
        if offline
        else AcquiescenceSection(
            status=MeasurementStatus.MEASURED,
            positively_framed_question=acquiescence_result.positively_framed_question,
            negatively_framed_question=acquiescence_result.negatively_framed_question,
            positive_agree_rate=acquiescence_result.positive_agree_rate,
            negative_agree_rate=acquiescence_result.negative_agree_rate,
            agreement_gap=acquiescence_result.agreement_gap,
        )
    )

    position_result = await run_position_bias_probe(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        base_path=root,
    )
    position_bias = (
        PositionBiasSection(
            status=MeasurementStatus.NOT_MEASURED_OFFLINE,
            reason=NOT_MEASURED_OFFLINE_REASON,
        )
        if offline
        else PositionBiasSection(
            status=MeasurementStatus.MEASURED,
            options=position_result.options,
            first_position_share_original_order=(
                position_result.first_position_share_original_order
            ),
            first_position_share_reversed_order=(
                position_result.first_position_share_reversed_order
            ),
            preference_shift=position_result.preference_shift,
        )
    )

    return ValidityReportModel(
        provider_name=provider_name,
        model=model,
        reproducibility=reproducibility,
        discriminative_validity=discriminative_validity,
        acquiescence_bias=acquiescence_bias,
        position_bias=position_bias,
        known_answer_calibration=known_answer_calibration,
        clustering_margin=measure_clustering_margin(),
        zero_vector_conflation=measure_zero_vector_conflation(),
        threshold_scaling=measure_threshold_scaling(),
    )


__all__ = ["run_validity_harness"]
