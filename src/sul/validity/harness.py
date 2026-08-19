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

**`provider` is checked against an explicit allow-list, not a negation.**
Only `FakeProvider` and `AnthropicProvider` (the cassette-backed real
adapter) may reach this function -- anything else, `ScriptedProvider`
above all, is rejected by type, before any dispatch. `ScriptedProvider` is a
content-aware test double (see `tests/support/scripted_provider.py`): it
answers a script derived from the actual prompt, so its output responds
sensibly to inputs and can look exactly like a real signal for §M6.2-.5,
without a cassette and without a live call -- the same failure this
milestone exists to prevent, reached by a worse route than `FakeProvider`'s
hash, because it produces numbers that pass a sanity check. `"anything that
isn't FakeProvider is accepted"` would let it straight through the moment
someone builds a recording script; the allow-list is what makes admitting
`AnthropicProvider` for real recording a one-line, explicit, reviewable
addition instead of a silent default.

**Reproducibility (§M6.1) is the one check this reasoning does not extend
to, and it is handled differently on purpose.** `CassetteTransport` matches
on `method + scrubbed_url + canonical_body` and replays one recorded
response per key. Same-seed, N-repeat reproducibility sends N *identical*
requests (same messages, same model, same everything the match key is built
from -- `seed` itself is never part of the wire body, so it can't
disambiguate them even if it mattered): recording collapses to one
surviving response (each repeat's write overwrites the last), and replay
returns that one response N times. A cassette cannot carry real
same-seed-repeat variance even in principle -- this is a structural property
of one-key-one-response replay, not a gap specific to `FakeProvider`.
Extending `CassetteTransport` to support multiple responses per key with
ordinal replay was considered and explicitly declined for this milestone
(it is an M2 change, needs its own cross-process determinism test, and
wasn't pre-approved). So `measure_reproducibility` is always called against
`FakeProvider`, unconditionally -- never against whatever `provider` this
function itself was given for the other four checks. Its number is real
(same-seed determinism is a genuine property of this pipeline) but, per its
own `caveat` field, not richly informative under any replay-based provider,
cassette included.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from sul.providers.anthropic import AnthropicProvider
from sul.providers.base import LLMProvider
from sul.providers.fake import FakeProvider
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

# Exactly two provider types may back `run_validity_harness`: `FakeProvider`
# (the default, offline path) and `AnthropicProvider` (the cassette-backed
# real path, gated behind explicit authorisation elsewhere). An allow-list,
# not a negation -- see the module docstring.
_ALLOWED_PROVIDER_TYPES: tuple[type, ...] = (FakeProvider, AnthropicProvider)


class UnsupportedValidityProviderError(TypeError):
    """`provider` was not one of `_ALLOWED_PROVIDER_TYPES`.

    Raised before any dispatch -- most pointedly against
    `tests.support.scripted_provider.ScriptedProvider`, which is legitimate
    as a negative-control test double but must never be reachable from
    `run_validity_harness`/`sul validate` (see the module docstring).
    """

    def __init__(self, provider: object) -> None:
        self.provider_type = type(provider)
        allowed = ", ".join(t.__name__ for t in _ALLOWED_PROVIDER_TYPES)
        super().__init__(
            f"run_validity_harness does not accept provider type "
            f"{self.provider_type.__name__!r}; only {allowed} are allowed."
        )


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
    if not isinstance(provider, _ALLOWED_PROVIDER_TYPES):
        raise UnsupportedValidityProviderError(provider)

    root = base_path if base_path is not None else Path.cwd()
    offline = _is_offline_provider(provider_name)

    # Always FakeProvider, regardless of `provider`/`provider_name` above --
    # see the module docstring: a cassette cannot carry same-seed-repeat
    # variance even in principle, so there is nothing a real/cassette-backed
    # provider would add here that FakeProvider doesn't already give.
    reproducibility = await measure_reproducibility(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
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
            provenance=discriminative_result.provenance,
        )
        if offline
        else DiscriminativeValiditySection(
            status=MeasurementStatus.MEASURED,
            bad_blocker_confusion_count=discriminative_result.bad_blocker_confusion_count,
            good_blocker_confusion_count=discriminative_result.good_blocker_confusion_count,
            material_difference=discriminative_result.material_difference,
            provenance=discriminative_result.provenance,
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
            # M6.5 reads the same bad-artefact rows §M6.2 already produced
            # (see the module docstring in `sul.validity.calibration`) --
            # same underlying ModelCalls, same provenance.
            provenance=discriminative_result.provenance,
        )
        if offline
        else KnownAnswerCalibrationSection(
            status=MeasurementStatus.MEASURED,
            total_defects=calibration_result.total_defects,
            detected_count=calibration_result.detected_count,
            detection_rate=calibration_result.detection_rate,
            per_defect=calibration_result.per_defect,
            provenance=discriminative_result.provenance,
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
            provenance=acquiescence_result.provenance,
        )
        if offline
        else AcquiescenceSection(
            status=MeasurementStatus.MEASURED,
            positively_framed_question=acquiescence_result.positively_framed_question,
            negatively_framed_question=acquiescence_result.negatively_framed_question,
            positive_agree_rate=acquiescence_result.positive_agree_rate,
            negative_agree_rate=acquiescence_result.negative_agree_rate,
            agreement_gap=acquiescence_result.agreement_gap,
            provenance=acquiescence_result.provenance,
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
            provenance=position_result.provenance,
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
            provenance=position_result.provenance,
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
