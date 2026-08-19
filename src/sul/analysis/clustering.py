"""TF-IDF + agglomerative clustering over `Finding.summary` text
(PROJECT_SPEC.md §M5). No LLM call, no `ModelClient`, no seed derivation --
`sklearn`'s clustering is deterministic given identical input, so the only
determinism this module owns is making sure the *input* and the *label
numbering* are independent of database row order.

**Never deletes, merges or rewrites a `Finding` row.** This module takes an
in-memory sequence of `FindingRow` and returns an in-memory
`ClusterAssignment` list; nothing here touches the database. "Deduplicate" is
what the report renderer does with these assignments (one entry per cluster),
not something this module does to the underlying rows -- see the M5 plan and
the deviation note on `Finding.cluster_id` in PROJECT_SPEC.md.

**Metric/linkage.** `metric="cosine"`, `linkage="average"`. Ward requires a
Euclidean metric and biases toward equal-sized, spherical clusters -- wrong
for finding themes, which are naturally lopsided (one large theme, several
singletons). Cosine is length-invariant, which matters because Analyst
summaries vary a lot in length. Average linkage is the stable middle ground
between single (chains outliers into a cluster through one weak link) and
complete (over-sensitive to one distant member) once the metric is cosine.

**Threshold and a known limitation of the method.** `tests/test_clustering.py`
builds a discrimination fixture *before* the default threshold was chosen
(see `sul.analysis.config`): near-duplicate paraphrases of one problem, and
distinct problems phrased in the same uniform "Analyst voice" one prompt
template produces. Both directions pass at threshold 0.6, but the margin is
asymmetric -- the near-duplicate cluster's internal distances top out around
0.45, while the closest "must stay apart" pair sits at only ~0.65. That's
because TF-IDF cosine over Analyst-authored summaries partly measures the
Analyst's phrasing uniformity (shared sentence templates, shared register)
rather than the panel's actual agreement, which inflates similarity between
*unrelated* findings for reasons that have nothing to do with substance. This
is a property of the method, not a bug in this implementation -- it is
exactly the kind of thing M6's validity harness exists to measure, not
something a threshold tweak can fix.

**Determinism.** `AgglomerativeClustering`'s raw integer labels are a
function of input row order (an implementation detail of the algorithm, not
a documented contract) -- verified by hand: the same 7-summary fixture
`tests/test_clustering.py` uses produces raw labels `[0,0,0,4,3,1,2]` fed
forward and `[2,3,4,1,0,0,0]` fed in reverse, and in neither case does the
label order match ascending finding id. What actually makes the returned
`cluster_id`s independent of row order is the renumbering step below:
clusters are renumbered by the ascending `Finding.id` of their lowest-id
member, read directly off each member's own `.finding_id` attribute rather
than its position in the input list -- so the cluster containing the
overall-lowest finding id always becomes cluster 0, regardless of what order
`rows` arrived in. `tests/test_clustering.py
::test_cluster_ids_ascend_by_minimum_member_finding_id` asserts this
directly (mins must come out ascending), rather than via set-equality
between a forward and a reversed call, which a small fixture can satisfy by
coincidence even with the renumbering step removed -- this was caught by
hand during development: an earlier version of that test used set-equality
and stayed green with renumbering deliberately broken.

Findings are also sorted by `Finding.id` up front (`ordered`), before
vectorising -- and this sort is load-bearing, not redundant defence-in-depth.
Renumbering (above) only fixes up cluster *labels* to be order-independent;
it does not fix up the *partition* those labels describe.
`AgglomerativeClustering` breaks tied merge distances by array position, and this corpus
deliberately contains the cases that produce exact ties -- textually
identical findings, and multiple zero-vector rows. Feeding rows in a
different order can therefore merge a different set of tied rows into the
same cluster, not just relabel an identical partition differently. Sorting
by `Finding.id` up front fixes that array order deterministically, which is
what keeps the *partition itself* -- not just its numbering -- independent
of the order rows arrived in. (An earlier version of this docstring
described this sort as redundant, on the evidence that removing it left the
suite green; that was a fact about this fixture's particular tie structure
at the time it was checked, not a property of the algorithm -- a fixture
without exact ties would pass either way and prove nothing about this.)
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel, ConfigDict
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances

from sul.analysis.config import ClusteringConfig
from sul.enums import FindingCategory


class FindingRow(BaseModel):
    """One finding plus the joined fields the analysis/report layer needs,
    already resolved from the database -- this module never queries.
    """

    model_config = ConfigDict(extra="forbid")

    finding_id: int
    run_id: int
    persona_id: int
    persona_name: str
    segment: str
    category: FindingCategory
    severity: int
    summary: str
    evidence_turn_id: int
    evidence_content: str
    evidence_turn_ordinal: int


class ClusterAssignment(BaseModel):
    """One cluster's membership and deterministically-derived title."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: int
    finding_ids: tuple[int, ...]
    title: str


def cluster_findings(
    rows: list[FindingRow], config: ClusteringConfig
) -> list[ClusterAssignment]:
    """Cluster `rows` by `Finding.summary` text similarity.

    Degenerate inputs, handled explicitly rather than left to raise or to an
    accidental code path:

    - zero rows -> `[]`
    - one row -> that row as its own singleton cluster, no `sklearn` call
      (`AgglomerativeClustering` requires at least 2 samples)
    - a corpus whose vocabulary is empty after stop-word removal (every
      summary is stop words only) -> `TfidfVectorizer` raises `ValueError`;
      caught explicitly and reported as one singleton cluster per finding
    - one summary's vector is all-zero even though the *corpus* has a
      non-empty vocabulary (a summary short enough, or generic enough, that
      every token it contains was excluded -- sklearn's default token
      pattern alone excludes single-character tokens, before stop words are
      even considered) -- cosine distance is undefined for a zero vector
      (`sklearn` raises `ValueError: Cosine affinity cannot be used when X
      contains zero vectors`), discovered by the cross-process determinism
      test against `FakeProvider`'s synthesised summaries, not invented
      up front. Handled the same way as the empty-vocabulary case, but
      per-row rather than for the whole batch: a zero-vector row becomes its
      own singleton, while every other row still clusters normally against
      each other -- one degenerate summary should not flatten every other
      finding in the study to singletons too.

    None of these ever raises out of this function or silently drops a
    finding.
    """
    if not rows:
        return []

    ordered = sorted(rows, key=lambda r: r.finding_id)

    if len(ordered) == 1:
        only = ordered[0]
        return [
            ClusterAssignment(
                cluster_id=0, finding_ids=(only.finding_id,), title=only.summary
            )
        ]

    texts = [r.summary for r in ordered]
    vectorizer = TfidfVectorizer(stop_words=config.stop_words, min_df=config.min_df)
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return [
            ClusterAssignment(
                cluster_id=i, finding_ids=(r.finding_id,), title=r.summary
            )
            for i, r in enumerate(ordered)
        ]

    dense = matrix.toarray()
    row_norms = np.linalg.norm(dense, axis=1)
    zero_positions = [i for i, n in enumerate(row_norms) if n == 0.0]
    nonzero_positions = [i for i, n in enumerate(row_norms) if n != 0.0]

    groups: list[list[int]] = [[i] for i in zero_positions]

    if len(nonzero_positions) == 1:
        groups.append(nonzero_positions)
    elif len(nonzero_positions) >= 2:
        submatrix = dense[nonzero_positions]
        model = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=config.distance_threshold,
            metric=config.metric,
            linkage=config.linkage,
        )
        raw_labels = model.fit_predict(submatrix)
        by_raw_label: dict[int, list[int]] = defaultdict(list)
        for sub_index, raw_label in enumerate(raw_labels):
            by_raw_label[int(raw_label)].append(nonzero_positions[sub_index])
        groups.extend(by_raw_label.values())

    group_min_finding_id = {
        group_index: min(ordered[i].finding_id for i in indices)
        for group_index, indices in enumerate(groups)
    }
    renumbering = {
        group_index: new_id
        for new_id, group_index in enumerate(
            sorted(range(len(groups)), key=lambda gi: group_min_finding_id[gi])
        )
    }

    assignments: list[ClusterAssignment] = [
        ClusterAssignment(cluster_id=0, finding_ids=(), title="")
    ] * len(groups)
    for group_index, indices in enumerate(groups):
        member_indices = sorted(indices, key=lambda i: ordered[i].finding_id)
        finding_ids = tuple(ordered[i].finding_id for i in member_indices)
        if len(member_indices) == 1:
            title = ordered[member_indices[0]].summary
        else:
            centroid = dense[member_indices].mean(axis=0, keepdims=True)
            distances_to_centroid = cosine_distances(dense[member_indices], centroid)[
                :, 0
            ]
            title_position = int(np.argmin(distances_to_centroid))
            title = ordered[member_indices[title_position]].summary
        new_id = renumbering[group_index]
        assignments[new_id] = ClusterAssignment(
            cluster_id=new_id, finding_ids=finding_ids, title=title
        )

    return assignments


__all__ = ["ClusterAssignment", "FindingRow", "cluster_findings"]
