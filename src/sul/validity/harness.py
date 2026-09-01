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

**Section-level containment (§M6 Deviation 11).** §M6.2-.4's three checks
(discriminative validity + the calibration measurement derived from it,
acquiescence, position bias) are each wrapped in
`except (ProviderError, StructuredOutputError)`, so a section that fails
outright (a transient network failure, a `RateLimited` that survives
`call_with_backoff`'s retries, or any other provider failure that escapes
`sul.validity.acquiescence`/`.position`'s own per-subject containment)
degrades to `PARTIALLY_MEASURED` with the exception recorded as its reason,
while the sections that already succeeded -- and every already-dispatched,
already-billed `ModelCall` behind them -- survive into the returned
`ValidityReportModel`. This is §M4's "exits cleanly with partial results
saved" contract (`sul.runner.orchestrator`'s module docstring) applied one
level up, at the harness rather than the run.

**Reproducibility (§M6.1) is deliberately excluded from that containment.**
`ReproducibilitySection` (`sul.validity.model`) has no `status` field --
"Always `measured`" is baked into its own docstring, unlike every other
section here -- so there is no value this function could assign it on
failure without changing that model. It is also always dispatched against a
freshly constructed `FakeProvider()`, never the harness-level `provider`, so
a `ProviderError`/`StructuredOutputError` from a real or cassette-backed
provider cannot reach it in the first place; the only way this call fails is
a genuine bug in this codebase's own deterministic synthesis path, which
containment should not paper over.

**Reproducibility (§M6.1) is also the one check the offline/online split
does not extend to, and it is handled differently on purpose.**
`CassetteTransport` matches
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

from sul.enums import AgentRole
from sul.providers.anthropic import AnthropicProvider
from sul.providers.base import LLMProvider, ProviderError
from sul.providers.client import StructuredOutputError
from sul.providers.fake import FakeProvider
from sul.validity.acquiescence import AcquiescenceResult, run_acquiescence_probe
from sul.validity.calibration import measure_known_answer_calibration
from sul.validity.discriminative import (
    DiscriminativeValidityResult,
    run_discriminative_validity,
)
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
from sul.validity.position import PositionBiasResult, run_position_bias_probe
from sul.validity.reproducibility import measure_reproducibility
from sul.validity.sentinel import (
    NOT_MEASURED_OFFLINE_REASON,
    MeasurementStatus,
    partially_measured_personas_reason,
    partially_measured_reason,
)

# Section-level containment (§M6 Deviation 11): the same tuple
# `sul.validity.acquiescence`/`.position` catch per-subject, applied one
# level up, around a whole section's dispatch.
_SECTION_FAILURE_EXCEPTIONS = (ProviderError, StructuredOutputError)

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


def _probe_status(
    *, offline: bool, subjects_attempted: int, subjects_measured: int
) -> tuple[MeasurementStatus, str | None]:
    """Resolve an acquiescence/position-bias section's three-way status from
    its subject counts alone (PROJECT_SPEC.md §M6 Deviation 11). Zero
    survivors (`subjects_measured == 0`) still resolves to
    `PARTIALLY_MEASURED`, not `NOT_MEASURED_OFFLINE` -- see
    `sul.validity.sentinel`'s module docstring for why reusing that member's
    "offline" framing for a real-provider section that simply lost every
    subject would misdescribe it.
    """
    if offline:
        return MeasurementStatus.NOT_MEASURED_OFFLINE, NOT_MEASURED_OFFLINE_REASON
    if subjects_measured < subjects_attempted:
        return (
            MeasurementStatus.PARTIALLY_MEASURED,
            partially_measured_reason(
                attempted=subjects_attempted, measured=subjects_measured
            ),
        )
    return MeasurementStatus.MEASURED, None


def _discriminative_status(
    *,
    offline: bool,
    bad_attempted: int,
    bad_completed: int,
    good_attempted: int,
    good_completed: int,
) -> tuple[MeasurementStatus, str | None]:
    """Resolve `DiscriminativeValiditySection`'s status from two independent
    persona-completion denominators (PROJECT_SPEC.md §M6 Deviation 19) --
    one bad-artefact study, one good-artefact study, either of which can
    lose a persona independently of the other. Reuses `_probe_status` as-is
    for the three-way status decision on each artefact (offline /
    dropout / full), but never its `reason`: that string is written for
    §M6.3/§M6.4's single-shot probe calls ("subjects... completed every
    probe call"), which would misdescribe a §M6.2 turn-loop persona run --
    see `partially_measured_personas_reason`, this section's own sibling.
    Any dropout on either artefact degrades the whole section to
    `PARTIALLY_MEASURED` (no tolerance threshold: the denominator printed
    beside the count is the disclosure; where it stops being useful is the
    reader's call, not this function's).
    """
    bad_status, _ = _probe_status(
        offline=offline,
        subjects_attempted=bad_attempted,
        subjects_measured=bad_completed,
    )
    good_status, _ = _probe_status(
        offline=offline,
        subjects_attempted=good_attempted,
        subjects_measured=good_completed,
    )
    if offline:
        return MeasurementStatus.NOT_MEASURED_OFFLINE, NOT_MEASURED_OFFLINE_REASON

    reasons = []
    if bad_status == MeasurementStatus.PARTIALLY_MEASURED:
        reasons.append(
            partially_measured_personas_reason(
                artefact="bad", attempted=bad_attempted, completed=bad_completed
            )
        )
    if good_status == MeasurementStatus.PARTIALLY_MEASURED:
        reasons.append(
            partially_measured_personas_reason(
                artefact="good", attempted=good_attempted, completed=good_completed
            )
        )
    if reasons:
        return MeasurementStatus.PARTIALLY_MEASURED, " ".join(reasons)
    return MeasurementStatus.MEASURED, None


async def run_validity_harness(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    model_by_agent: dict[AgentRole, str] | None = None,
    base_path: Path | None = None,
    max_cost_usd: float | None = None,
) -> ValidityReportModel:
    """`model_by_agent`, passed straight through to §M6.2's discriminative
    validity check (the only check with Persona/Moderator/Analyst turns --
    §M6.3/§M6.4's probes and §M6.1's reproducibility each dispatch a single
    `AgentRole`, so a per-agent override has nothing to differentiate there),
    optionally overrides `model` per `AgentRole`. Omitted (the default),
    every agent dispatches on `model`, unchanged from before this parameter
    existed.

    `max_cost_usd` (§M6 Deviation 11), when given, is passed unchanged to
    each of the three provider-dispatching checks below -- discriminative
    validity (which spends it twice, once per artefact study, per
    `sul.validity.discriminative.run_discriminative_validity`'s own
    docstring), acquiescence, and position bias. It is a **per-check**
    ceiling, not a shared whole-harness total: four independent budget
    guards (discriminative validity's two artefact studies, plus
    acquiescence, plus position bias) each given the same `max_cost_usd`
    can together spend up to roughly 4x it. Omitted (the default), every
    check's probe/study spend is unbounded, exactly as before this
    parameter existed.
    """
    if not isinstance(provider, _ALLOWED_PROVIDER_TYPES):
        raise UnsupportedValidityProviderError(provider)

    root = base_path if base_path is not None else Path.cwd()
    offline = _is_offline_provider(provider_name)

    # Always FakeProvider, regardless of `provider`/`provider_name` above --
    # see the module docstring: a cassette cannot carry same-seed-repeat
    # variance even in principle, so there is nothing a real/cassette-backed
    # provider would add here that FakeProvider doesn't already give. Never
    # wrapped in the section-level containment below -- see the module
    # docstring's "deliberately excluded" paragraph.
    reproducibility = await measure_reproducibility(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        base_path=root,
    )

    try:
        discriminative_result: (
            DiscriminativeValidityResult | None
        ) = await run_discriminative_validity(
            session_factory,
            provider=provider,
            provider_name=provider_name,
            model=model,
            model_by_agent=model_by_agent,
            base_path=root,
            max_cost_usd=max_cost_usd,
        )
    except _SECTION_FAILURE_EXCEPTIONS as exc:
        discriminative_result = None
        section_failure_reason = f"section failed before producing a result: {exc}"
        discriminative_validity = DiscriminativeValiditySection(
            status=MeasurementStatus.PARTIALLY_MEASURED,
            reason=section_failure_reason,
            provenance=[],
        )
        known_answer_calibration = KnownAnswerCalibrationSection(
            status=MeasurementStatus.PARTIALLY_MEASURED,
            reason=(
                "§M6.5 reads the bad-artefact rows §M6.2 produces; "
                f"{section_failure_reason}"
            ),
            total_defects=measure_known_answer_calibration([]).total_defects,
            provenance=[],
        )
    else:
        # narrows for mypy; try/else guarantees this is set
        assert discriminative_result is not None
        disc_status, disc_reason = _discriminative_status(
            offline=offline,
            bad_attempted=discriminative_result.bad_personas_attempted,
            bad_completed=discriminative_result.bad_personas_completed,
            good_attempted=discriminative_result.good_personas_attempted,
            good_completed=discriminative_result.good_personas_completed,
        )
        discriminative_validity = (
            DiscriminativeValiditySection(
                status=disc_status,
                reason=disc_reason,
                provenance=discriminative_result.provenance,
            )
            if offline
            else DiscriminativeValiditySection(
                status=disc_status,
                reason=disc_reason,
                bad_blocker_confusion_count=(
                    discriminative_result.bad_blocker_confusion_count
                ),
                good_blocker_confusion_count=(
                    discriminative_result.good_blocker_confusion_count
                ),
                material_difference=discriminative_result.material_difference,
                bad_personas_attempted=discriminative_result.bad_personas_attempted,
                bad_personas_completed=discriminative_result.bad_personas_completed,
                good_personas_attempted=discriminative_result.good_personas_attempted,
                good_personas_completed=discriminative_result.good_personas_completed,
                bad_category_counts=discriminative_result.bad_category_counts,
                good_category_counts=discriminative_result.good_category_counts,
                bad_distinct_anchor_count=(
                    discriminative_result.bad_distinct_anchor_count
                ),
                good_distinct_anchor_count=(
                    discriminative_result.good_distinct_anchor_count
                ),
                provenance=discriminative_result.provenance,
            )
        )

        calibration_result = measure_known_answer_calibration(
            discriminative_result.bad_rows
        )
        # Calibration inherits the bad-artefact study's own denominator
        # rather than computing (or combining) one of its own (PROJECT_SPEC.md
        # §M6 Deviation 19): it reads discriminative_result.bad_rows
        # directly, so a bad-artefact persona dropout affects both sections
        # identically -- the good-artefact denominator plays no part here.
        if offline:
            calib_status, calib_reason = (
                MeasurementStatus.NOT_MEASURED_OFFLINE,
                NOT_MEASURED_OFFLINE_REASON,
            )
        elif (
            discriminative_result.bad_personas_completed
            < discriminative_result.bad_personas_attempted
        ):
            calib_status = MeasurementStatus.PARTIALLY_MEASURED
            calib_reason = partially_measured_personas_reason(
                artefact="bad",
                attempted=discriminative_result.bad_personas_attempted,
                completed=discriminative_result.bad_personas_completed,
            )
        else:
            calib_status, calib_reason = MeasurementStatus.MEASURED, None

        known_answer_calibration = (
            KnownAnswerCalibrationSection(
                status=calib_status,
                reason=calib_reason,
                total_defects=calibration_result.total_defects,
                personas_attempted=discriminative_result.bad_personas_attempted,
                personas_completed=discriminative_result.bad_personas_completed,
                # M6.5 reads the same bad-artefact rows §M6.2 already
                # produced (see the module docstring in
                # `sul.validity.calibration`) -- same underlying ModelCalls,
                # same provenance.
                provenance=discriminative_result.provenance,
            )
            if offline
            else KnownAnswerCalibrationSection(
                status=calib_status,
                reason=calib_reason,
                total_defects=calibration_result.total_defects,
                detected_count=calibration_result.detected_count,
                detection_rate=calibration_result.detection_rate,
                per_defect=calibration_result.per_defect,
                personas_attempted=discriminative_result.bad_personas_attempted,
                personas_completed=discriminative_result.bad_personas_completed,
                provenance=discriminative_result.provenance,
            )
        )

    try:
        acquiescence_result: AcquiescenceResult | None = await run_acquiescence_probe(
            session_factory,
            provider=provider,
            provider_name=provider_name,
            model=model,
            base_path=root,
            max_cost_usd=max_cost_usd,
        )
    except _SECTION_FAILURE_EXCEPTIONS as exc:
        acquiescence_result = None
        acquiescence_bias = AcquiescenceSection(
            status=MeasurementStatus.PARTIALLY_MEASURED,
            reason=f"section failed before producing a result: {exc}",
            provenance=[],
        )
    else:
        # narrows for mypy; try/else guarantees this is set
        assert acquiescence_result is not None
        acq_status, acq_reason = (
            (MeasurementStatus.NOT_MEASURED_OFFLINE, NOT_MEASURED_OFFLINE_REASON)
            if offline
            else _probe_status(
                offline=False,
                subjects_attempted=acquiescence_result.subjects_attempted,
                subjects_measured=acquiescence_result.subjects_measured,
            )
        )
        has_rates = not offline and acquiescence_result.subjects_measured > 0
        acquiescence_bias = AcquiescenceSection(
            status=acq_status,
            reason=acq_reason,
            positively_framed_question=(
                None if offline else acquiescence_result.positively_framed_question
            ),
            negatively_framed_question=(
                None if offline else acquiescence_result.negatively_framed_question
            ),
            positive_agree_rate=(
                acquiescence_result.positive_agree_rate if has_rates else None
            ),
            negative_agree_rate=(
                acquiescence_result.negative_agree_rate if has_rates else None
            ),
            agreement_gap=acquiescence_result.agreement_gap if has_rates else None,
            subjects_attempted=(
                None if offline else acquiescence_result.subjects_attempted
            ),
            subjects_measured=(
                None if offline else acquiescence_result.subjects_measured
            ),
            provenance=acquiescence_result.provenance,
        )

    try:
        position_result: PositionBiasResult | None = await run_position_bias_probe(
            session_factory,
            provider=provider,
            provider_name=provider_name,
            model=model,
            base_path=root,
            max_cost_usd=max_cost_usd,
        )
    except _SECTION_FAILURE_EXCEPTIONS as exc:
        position_result = None
        position_bias = PositionBiasSection(
            status=MeasurementStatus.PARTIALLY_MEASURED,
            reason=f"section failed before producing a result: {exc}",
            provenance=[],
        )
    else:
        # narrows for mypy; try/else guarantees this is set
        assert position_result is not None
        pos_status, pos_reason = (
            (MeasurementStatus.NOT_MEASURED_OFFLINE, NOT_MEASURED_OFFLINE_REASON)
            if offline
            else _probe_status(
                offline=False,
                subjects_attempted=position_result.subjects_attempted,
                subjects_measured=position_result.subjects_measured,
            )
        )
        has_shares = not offline and position_result.subjects_measured > 0
        position_bias = PositionBiasSection(
            status=pos_status,
            reason=pos_reason,
            options=None if offline else position_result.options,
            first_position_share_original_order=(
                position_result.first_position_share_original_order
                if has_shares
                else None
            ),
            first_position_share_reversed_order=(
                position_result.first_position_share_reversed_order
                if has_shares
                else None
            ),
            preference_shift=(position_result.preference_shift if has_shares else None),
            subjects_attempted=(
                None if offline else position_result.subjects_attempted
            ),
            subjects_measured=None if offline else position_result.subjects_measured,
            provenance=position_result.provenance,
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
