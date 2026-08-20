"""`ValidityReportModel`: everything `sul.validity.markdown` and
`sul.validity.limitations` render from, mirroring `sul.report.model`'s own
"one model, no field from wall-clock/introspection" discipline (no
`generated_at`; `provider_name`/`model` are recorded because they're
provenance the reader needs to interpret the numbers, not runtime noise).

Every content-dependent section (`discriminative_validity`, `acquiescence_bias`,
`position_bias`, `known_answer_calibration`) carries a `status:
MeasurementStatus` and is `None` everywhere except `status`/`reason` when
`NOT_MEASURED_OFFLINE` -- see `sul.validity.sentinel` for why that has to be a
distinct enum value, not an absent/zero field.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from sul.validity.sentinel import MeasurementStatus


class AgentProvenance(BaseModel):
    """Which provider/model actually produced one agent role's calls for a
    section's underlying data -- read back from the `ModelCall` audit trail
    (`sul.validity.data.load_provenance`), not threaded through as a
    separate "what was requested" value. A rendered *field* on every
    content-dependent section (and reproducibility), never prose in a
    caveat above or below a table: after a mixed run (some sections
    FakeProvider, others a cassette-backed real model, possibly a different
    model per agent role), a reader must be able to tell which is which
    from the row itself.
    """

    model_config = ConfigDict(extra="forbid")

    agent: str
    provider: str
    model: str


REPRODUCIBILITY_CAVEAT = (
    "Zero variance and a 1.0 mean top-5 cluster Jaccard overlap here are "
    "structurally guaranteed by FakeProvider's deterministic hashing "
    "(derive_seed feeds a pure sha256-keyed synthesis, replayed identically "
    "for the same seed) -- this measures the harness's own determinism, not "
    "the panel's. This check always runs against FakeProvider, permanently, "
    "regardless of what provider backs the other four checks: "
    "CassetteTransport replays one recorded response per request, so a "
    "cassette cannot carry real same-seed-repeat variance even in "
    "principle (N identical requests -> one surviving recorded response, "
    "replayed N times). A live, uncassetted run against a real provider "
    "could show non-zero variance -- that would be expected, not a failure "
    "(PROJECT_SPEC.md §M6.1: 'non-zero variance is fine; unreported "
    "variance is not') -- but this harness never performs one."
)


class SeedSensitivitySection(BaseModel):
    """Optional addition to M6.1: N repeats across *different* seeds (not the
    same one), which is offline-meaningful because FakeProvider's hash
    includes the seed -- unlike same-seed reproducibility, this is not
    structurally forced to a fixed answer. Measures how much the
    clustering/ranking pipeline amplifies input variation, not panel realism.
    """

    model_config = ConfigDict(extra="forbid")

    seeds_tried: int
    finding_count_range: tuple[int, int]
    cluster_count_range: tuple[int, int]
    mean_top5_cluster_jaccard: float


class ReproducibilitySection(BaseModel):
    """PROJECT_SPEC.md §M6.1. Always `measured` -- offline, this metric is
    genuinely computable, just not richly informative (see `caveat`, printed
    adjacent to the numbers in every renderer, never a separate footnote).
    """

    model_config = ConfigDict(extra="forbid")

    repeats: int
    finding_count_variance: float
    mean_top5_cluster_jaccard: float
    caveat: str = REPRODUCIBILITY_CAVEAT
    seed_sensitivity: SeedSensitivitySection
    provenance: list[AgentProvenance]


class DiscriminativeValiditySection(BaseModel):
    """PROJECT_SPEC.md §M6.2."""

    model_config = ConfigDict(extra="forbid")

    status: MeasurementStatus
    reason: str | None = None
    bad_blocker_confusion_count: int | None = None
    good_blocker_confusion_count: int | None = None
    material_difference: bool | None = None
    provenance: list[AgentProvenance]


class AcquiescenceSection(BaseModel):
    """PROJECT_SPEC.md §M6.3.

    `subjects_attempted`/`subjects_measured` (§M6 Deviation 11) are the
    denominator behind the rates below -- populated whenever `status` is
    `MEASURED` or `PARTIALLY_MEASURED` (never for `NOT_MEASURED_OFFLINE`,
    where no probe call was dispatched at all). Equal when `status` is
    `MEASURED`; `subjects_measured < subjects_attempted` is exactly what
    `PARTIALLY_MEASURED` means.
    """

    model_config = ConfigDict(extra="forbid")

    status: MeasurementStatus
    reason: str | None = None
    positively_framed_question: str | None = None
    negatively_framed_question: str | None = None
    positive_agree_rate: float | None = None
    negative_agree_rate: float | None = None
    agreement_gap: float | None = None
    subjects_attempted: int | None = None
    subjects_measured: int | None = None
    provenance: list[AgentProvenance]


class PositionBiasSection(BaseModel):
    """PROJECT_SPEC.md §M6.4. See `AcquiescenceSection` for what
    `subjects_attempted`/`subjects_measured` mean.
    """

    model_config = ConfigDict(extra="forbid")

    status: MeasurementStatus
    reason: str | None = None
    options: tuple[str, ...] | None = None
    first_position_share_original_order: float | None = None
    first_position_share_reversed_order: float | None = None
    preference_shift: float | None = None
    subjects_attempted: int | None = None
    subjects_measured: int | None = None
    provenance: list[AgentProvenance]


class DefectResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    defect_id: str
    description: str
    detected: bool


class KnownAnswerCalibrationSection(BaseModel):
    """PROJECT_SPEC.md §M6.5. Named "calibration" by the spec's own header;
    the criterion it specifies is recall against a fixed known-answer set
    ("detection rate"), not confidence calibration -- see the M6
    implementation note in PROJECT_SPEC.md.
    """

    model_config = ConfigDict(extra="forbid")

    status: MeasurementStatus
    reason: str | None = None
    total_defects: int
    detected_count: int | None = None
    detection_rate: float | None = None
    per_defect: list[DefectResult] | None = None
    provenance: list[AgentProvenance]


class ClusteringMarginMeasurement(BaseModel):
    """`docs/limitations.md` weakness #1: TF-IDF cosine over Analyst-authored
    summaries partly measures phrasing uniformity, not panel agreement
    (documented in `sul.analysis.clustering`'s module docstring; M6 gives it
    a number).
    """

    model_config = ConfigDict(extra="forbid")

    near_duplicate_max_internal_distance: float
    distinct_pair_min_distance: float
    margin: float
    distance_threshold: float


class ZeroVectorConflationMeasurement(BaseModel):
    """`docs/limitations.md` weakness #2: a finding that vectorizes to an
    all-zero TF-IDF row becomes a singleton cluster, indistinguishable in the
    rendered report from a genuine frequency-1 theme.
    """

    model_config = ConfigDict(extra="forbid")

    zero_vector_singleton_count: int
    genuine_frequency_one_singleton_count: int
    total_singleton_clusters: int


class ThresholdScalingPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_count: int
    cluster_count: int
    mean_cluster_size: float


class ThresholdScalingMeasurement(BaseModel):
    """`docs/limitations.md` weakness #3 (optional 4th): how
    `distance_threshold=0.6`'s behaviour moves as corpus size grows.
    Measurement only -- the default is never changed here (PROJECT_SPEC.md's
    open items: "changing it changes comparability with every report
    produced so far").
    """

    model_config = ConfigDict(extra="forbid")

    distance_threshold: float
    points: list[ThresholdScalingPoint]


class ValidityReportModel(BaseModel):
    """Everything `sul.validity.markdown`/`limitations` render, and nothing
    else -- no live session, no field populated at render time.
    """

    model_config = ConfigDict(extra="forbid")

    provider_name: str
    model: str
    reproducibility: ReproducibilitySection
    discriminative_validity: DiscriminativeValiditySection
    acquiescence_bias: AcquiescenceSection
    position_bias: PositionBiasSection
    known_answer_calibration: KnownAnswerCalibrationSection
    clustering_margin: ClusteringMarginMeasurement
    zero_vector_conflation: ZeroVectorConflationMeasurement
    threshold_scaling: ThresholdScalingMeasurement


__all__ = [
    "REPRODUCIBILITY_CAVEAT",
    "AcquiescenceSection",
    "AgentProvenance",
    "ClusteringMarginMeasurement",
    "DefectResult",
    "DiscriminativeValiditySection",
    "KnownAnswerCalibrationSection",
    "PositionBiasSection",
    "ReproducibilitySection",
    "SeedSensitivitySection",
    "ThresholdScalingMeasurement",
    "ThresholdScalingPoint",
    "ValidityReportModel",
    "ZeroVectorConflationMeasurement",
]
