"""`sul.analysis.clustering` (PROJECT_SPEC.md §M5): degenerate inputs, stable
cluster numbering, and the discrimination fixture that grounds the default
`distance_threshold` (see `sul.analysis.config.ClusteringConfig` and
`sul.analysis.clustering`'s module docstring for the reasoning and the actual
cosine-distance numbers this fixture is built from).
"""

from __future__ import annotations

from sul.analysis.clustering import FindingRow, cluster_findings
from sul.analysis.config import ClusteringConfig
from sul.enums import FindingCategory


def _row(
    finding_id: int,
    summary: str,
    *,
    persona_id: int = 1,
    run_id: int | None = None,
    category: FindingCategory = FindingCategory.BLOCKER,
    severity: int = 3,
) -> FindingRow:
    return FindingRow(
        finding_id=finding_id,
        run_id=run_id if run_id is not None else persona_id,
        persona_id=persona_id,
        persona_name=f"persona-{persona_id}",
        segment="seg",
        category=category,
        severity=severity,
        summary=summary,
        evidence_turn_id=finding_id * 10,
        evidence_content="the persona said something",
        evidence_turn_ordinal=1,
    )


def test_zero_findings_returns_empty() -> None:
    assert cluster_findings([], ClusteringConfig()) == []


def test_one_finding_is_its_own_cluster_without_calling_sklearn() -> None:
    row = _row(1, "the submit button could not be found")
    assignments = cluster_findings([row], ClusteringConfig())
    assert len(assignments) == 1
    assert assignments[0].cluster_id == 0
    assert assignments[0].finding_ids == (1,)
    assert assignments[0].title == row.summary


def test_identical_text_collapses_to_one_cluster() -> None:
    rows = [
        _row(i, "the price on the page did not match checkout") for i in range(1, 5)
    ]
    assignments = cluster_findings(rows, ClusteringConfig())
    assert len(assignments) == 1
    assert set(assignments[0].finding_ids) == {1, 2, 3, 4}


def test_empty_vocabulary_after_stopword_removal_falls_back_to_singletons() -> None:
    # Every one of these is stop-words-only under sklearn's English list, so
    # TfidfVectorizer(stop_words="english") raises "empty vocabulary" -- the
    # fallback must catch it, not crash, and must not silently drop findings.
    rows = [_row(1, "it was the"), _row(2, "and if not")]
    assignments = cluster_findings(rows, ClusteringConfig())
    assert {fid for a in assignments for fid in a.finding_ids} == {1, 2}
    assert len(assignments) == 2  # singleton fallback, not merged


def test_single_zero_vector_summary_is_a_singleton_without_flattening_other_rows() -> (
    None
):
    """One summary short/generic enough to vectorise to an all-zero row (a
    single one-character token: sklearn's default token pattern excludes
    single-character tokens before stop words are even considered) must not
    raise (`cosine` distance is undefined for a zero vector) and must not
    flatten every other, perfectly clusterable row to singletons too --
    found via the cross-process determinism test against FakeProvider's
    synthesised summaries, not anticipated up front.
    """
    rows = [
        _row(1, "x"),  # tokenises to nothing -> all-zero TF-IDF row
        _row(
            2, "the persona was unable to locate the submit button on the signup form"
        ),
        _row(3, "the persona could not find the submit button on the signup form"),
    ]
    assignments = cluster_findings(rows, ClusteringConfig())
    cluster_of = {fid: a.cluster_id for a in assignments for fid in a.finding_ids}
    assert cluster_of[2] == cluster_of[3]
    assert cluster_of[1] != cluster_of[2]


def test_stable_renumbering_independent_of_input_order() -> None:
    rows = [
        _row(
            1, "the persona was unable to locate the submit button on the signup form"
        ),
        _row(
            2,
            "the persona could not find the submit button while completing the "
            "signup form",
        ),
        _row(
            3,
            "the persona was unable to locate the price confirmation on the "
            "checkout page",
        ),
    ]
    forward = cluster_findings(rows, ClusteringConfig())
    backward = cluster_findings(list(reversed(rows)), ClusteringConfig())

    def _as_set(assignments: list) -> set[tuple[int, tuple[int, ...]]]:
        return {(a.cluster_id, a.finding_ids) for a in assignments}

    assert _as_set(forward) == _as_set(backward)


def test_discrimination_fixture_near_dups_merge_and_distinct_problems_stay_apart() -> (
    None
):
    """Grounds the default `distance_threshold` (0.6): near-duplicate
    paraphrases of one problem must merge; distinct problems phrased in the
    same uniform "Analyst voice" (shared sentence template/register, the
    hazard called out in the M5 plan) must stay apart. See
    `sul.analysis.clustering`'s module docstring for the cosine-distance
    numbers behind this fixture and the margin between the two halves.
    """
    near_duplicates = [
        _row(
            1, "The persona was unable to locate the submit button on the signup form."
        ),
        _row(
            2,
            "The persona could not find the submit button while completing the "
            "signup form.",
        ),
        _row(
            3,
            "The persona struggled to find the submit button after filling in "
            "the signup form.",
        ),
    ]
    distinct_same_voice = [
        _row(
            4,
            "The persona was unable to locate the price confirmation on the "
            "checkout page.",
        ),
        _row(
            5,
            "The persona expressed distrust of the site after noticing no "
            "security badge near the payment field.",
        ),
        _row(
            6,
            "The persona abandoned the task after the required field was not "
            "visibly marked as mandatory.",
        ),
        _row(
            7,
            "The persona was pleasantly surprised by how quickly the trial "
            "signup completed.",
        ),
    ]

    assignments = cluster_findings(
        near_duplicates + distinct_same_voice, ClusteringConfig()
    )

    cluster_of = {fid: a.cluster_id for a in assignments for fid in a.finding_ids}

    assert cluster_of[1] == cluster_of[2] == cluster_of[3]
    distinct_clusters = {cluster_of[i] for i in (4, 5, 6, 7)}
    assert len(distinct_clusters) == 4
    assert cluster_of[1] not in distinct_clusters


def test_cluster_ids_ascend_by_minimum_member_finding_id() -> None:
    """`sklearn`'s raw labels are a function of input row order (verified by
    hand: this exact fixture produces `[0,0,0,4,3,1,2]` forward and
    `[2,3,4,1,0,0,0]` reversed) and do not come out in ascending
    min-finding-id order on their own. Renumbering by ascending min member
    `Finding.id` is the mechanism that fixes that -- this test asserts the
    renumbering contract directly, in both directions, rather than relying
    on set-equality between two calls (which a smaller fixture can satisfy
    by coincidence even with the renumbering step removed).
    """
    rows = [
        _row(
            1, "The persona was unable to locate the submit button on the signup form."
        ),
        _row(
            2,
            "The persona could not find the submit button while completing the "
            "signup form.",
        ),
        _row(
            3,
            "The persona struggled to find the submit button after filling in "
            "the signup form.",
        ),
        _row(
            4,
            "The persona was unable to locate the price confirmation on the "
            "checkout page.",
        ),
        _row(
            5,
            "The persona expressed distrust of the site after noticing no "
            "security badge near the payment field.",
        ),
        _row(
            6,
            "The persona abandoned the task after the required field was not "
            "visibly marked as mandatory.",
        ),
        _row(
            7,
            "The persona was pleasantly surprised by how quickly the trial "
            "signup completed.",
        ),
    ]
    for candidate in (rows, list(reversed(rows))):
        assignments = cluster_findings(candidate, ClusteringConfig())
        by_cluster_id = sorted(assignments, key=lambda a: a.cluster_id)
        mins = [min(a.finding_ids) for a in by_cluster_id]
        assert mins == sorted(mins), (
            f"cluster_ids must ascend by minimum member finding_id, got {mins}"
        )


def test_title_is_deterministic_closest_to_centroid_member() -> None:
    rows = [
        _row(1, "button missing on the form"),
        _row(2, "the submit button is missing from the signup form entirely"),
        _row(3, "no submit button visible anywhere on the signup form"),
    ]
    first = cluster_findings(rows, ClusteringConfig())
    second = cluster_findings(rows, ClusteringConfig())
    assert first == second
