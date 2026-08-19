"""Three offline-measurable weaknesses for `docs/limitations.md`
(PROJECT_SPEC.md §M6's acceptance: "at least two concrete, measured
weaknesses" -- all three ship because all three cost nothing extra to
measure, per the M6 design conversation's Correction 2). Every measurement
here is a genuine weakness of the panel's *analysis* pipeline, not of the
harness's ability to reach a real provider -- unlike §M6.2-.5, these don't
need FakeProvider gated behind a `NOT_MEASURED_OFFLINE` sentinel, because
they're properties of `sul.analysis.clustering`/`ClusteringConfig` exercised
against hand-built, deterministic text, not against anything an LLM produced.

1. Clustering margin: extends `tests/test_clustering.py`'s discrimination
   fixture with the actual cosine-distance numbers, not just a pass/fail.
2. Zero-vector conflation: a finding that vectorises to an all-zero TF-IDF
   row is indistinguishable, in a `ClusterAssignment`, from a genuine
   frequency-1 theme -- both come back as a singleton cluster.
3. Threshold scaling: how `distance_threshold=0.6`'s cluster count / mean
   cluster size move as corpus size grows. Measurement only -- the default is
   never changed here (`ClusteringConfig` and `sklearn.__version__` are
   embedded in `ReportModel` provenance; changing the default would break
   comparability with every report already produced, and PROJECT_SPEC.md's
   §M6 text never asks for a re-tuned default).
"""

from __future__ import annotations

import random

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances

from sul.analysis.clustering import FindingRow, cluster_findings
from sul.analysis.config import ClusteringConfig
from sul.enums import FindingCategory
from sul.validity.model import (
    ClusteringMarginMeasurement,
    ThresholdScalingMeasurement,
    ThresholdScalingPoint,
    ZeroVectorConflationMeasurement,
)


def _row(finding_id: int, summary: str) -> FindingRow:
    return FindingRow(
        finding_id=finding_id,
        run_id=finding_id,
        persona_id=finding_id,
        persona_name=f"persona-{finding_id}",
        segment="seg",
        category=FindingCategory.BLOCKER,
        severity=3,
        summary=summary,
        evidence_turn_id=finding_id * 10,
        evidence_content="the persona said something",
        evidence_turn_ordinal=1,
    )


def measure_clustering_margin(
    config: ClusteringConfig | None = None,
) -> ClusteringMarginMeasurement:
    """Same discrimination fixture shape as `tests/test_clustering.py`'s (near
    duplicates of one problem; distinct problems phrased in the same "Analyst
    voice"), read as raw cosine distances instead of just cluster membership.
    """
    config = config or ClusteringConfig()
    near_duplicates = [
        "The persona was unable to locate the submit button on the signup form.",
        "The persona could not find the submit button while completing the "
        "signup form.",
        "The persona struggled to find the submit button after filling in the "
        "signup form.",
    ]
    distinct_same_voice = [
        "The persona was unable to locate the price confirmation on the checkout page.",
        "The persona expressed distrust of the site after noticing no security "
        "badge near the payment field.",
        "The persona abandoned the task after the required field was not "
        "visibly marked as mandatory.",
        "The persona was pleasantly surprised by how quickly the trial signup "
        "completed.",
    ]
    texts = near_duplicates + distinct_same_voice
    n = len(near_duplicates)

    vectorizer = TfidfVectorizer(stop_words=config.stop_words, min_df=config.min_df)
    distances = cosine_distances(vectorizer.fit_transform(texts).toarray())

    should_merge = [(i, j) for i in range(n) for j in range(i + 1, n)]
    should_separate = [
        (i, j)
        for i in range(len(texts))
        for j in range(i + 1, len(texts))
        if not (i < n and j < n)
    ]

    max_internal = max(distances[i, j] for i, j in should_merge)
    min_separate = min(distances[i, j] for i, j in should_separate)

    return ClusteringMarginMeasurement(
        near_duplicate_max_internal_distance=float(max_internal),
        distinct_pair_min_distance=float(min_separate),
        margin=float(min_separate - max_internal),
        distance_threshold=config.distance_threshold,
    )


def _zero_vector_finding_ids(
    rows: list[FindingRow], config: ClusteringConfig
) -> set[int]:
    ordered = sorted(rows, key=lambda r: r.finding_id)
    texts = [r.summary for r in ordered]
    vectorizer = TfidfVectorizer(stop_words=config.stop_words, min_df=config.min_df)
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return {r.finding_id for r in ordered}
    norms = np.linalg.norm(matrix.toarray(), axis=1)
    return {ordered[i].finding_id for i, norm in enumerate(norms) if norm == 0.0}


def measure_zero_vector_conflation(
    config: ClusteringConfig | None = None,
) -> ZeroVectorConflationMeasurement:
    """A corpus with one genuinely zero-vector finding (a single-character
    token, excluded by sklearn's token pattern before stop words are even
    considered -- the exact hazard `sul.analysis.clustering`'s module
    docstring documents), one real near-duplicate pair, and one genuine
    one-off. All singleton clusters look identical in a `ClusterAssignment`;
    this measurement is what tells them apart from the outside.
    """
    config = config or ClusteringConfig()
    rows = [
        _row(1, "x"),
        _row(
            2, "the persona was unable to locate the submit button on the signup form"
        ),
        _row(3, "the persona could not find the submit button on the signup form"),
        _row(
            4,
            "the persona was pleasantly surprised by the onboarding checklist widget",
        ),
    ]
    assignments = cluster_findings(rows, config)
    singleton_clusters = [a for a in assignments if len(a.finding_ids) == 1]
    zero_vector_ids = _zero_vector_finding_ids(rows, config)

    zero_vector_singletons = sum(
        1 for a in singleton_clusters if a.finding_ids[0] in zero_vector_ids
    )
    return ZeroVectorConflationMeasurement(
        zero_vector_singleton_count=zero_vector_singletons,
        genuine_frequency_one_singleton_count=len(singleton_clusters)
        - zero_vector_singletons,
        total_singleton_clusters=len(singleton_clusters),
    )


_TEMPLATES = (
    "the persona could not find the {thing} on the {place}",
    "the persona was unable to locate the {thing} on the {place}",
    "the persona struggled to find the {thing} while using the {place}",
)
_THINGS = ("submit button", "price", "email field", "logout link", "help icon")
_PLACES = ("signup form", "checkout page", "settings page", "pricing table", "nav bar")


def _synthetic_corpus(n: int, *, seed: int = 12345) -> list[FindingRow]:
    """A deterministic (fixed `random.Random` seed, not `FakeProvider`)
    synthetic corpus of `n` findings drawn from a small template/vocabulary
    grid -- large enough to produce genuine repetition (and therefore
    genuine clusters) as `n` grows, without needing any LLM call.
    """
    rng = random.Random(seed)
    rows = []
    for i in range(1, n + 1):
        template = rng.choice(_TEMPLATES)
        thing = rng.choice(_THINGS)
        place = rng.choice(_PLACES)
        rows.append(_row(i, template.format(thing=thing, place=place)))
    return rows


def measure_threshold_scaling(
    finding_counts: tuple[int, ...] = (10, 25, 50, 100),
    config: ClusteringConfig | None = None,
) -> ThresholdScalingMeasurement:
    config = config or ClusteringConfig()
    points = []
    for n in finding_counts:
        rows = _synthetic_corpus(n)
        assignments = cluster_findings(rows, config)
        cluster_count = len(assignments)
        mean_size = n / cluster_count if cluster_count else 0.0
        points.append(
            ThresholdScalingPoint(
                finding_count=n,
                cluster_count=cluster_count,
                mean_cluster_size=mean_size,
            )
        )
    return ThresholdScalingMeasurement(
        distance_threshold=config.distance_threshold, points=points
    )


__all__ = [
    "measure_clustering_margin",
    "measure_threshold_scaling",
    "measure_zero_vector_conflation",
]
