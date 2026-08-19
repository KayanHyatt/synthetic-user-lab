"""PROJECT_SPEC.md §M6.1: same seed, same model, N repeats. Reports variance
in finding counts and mean top-5 cluster Jaccard overlap across repeats, plus
an optional seed-sensitivity addition (different seeds, not the same one --
see `SeedSensitivitySection`'s docstring in `sul.validity.model`).

Both checks reuse M4's `materialize_study`/`run_study` and M5's
`cluster_findings`/`rank_clusters` unmodified -- this module only adds the
repeat loop and the cross-repeat comparison, which is genuinely new (M5 never
compares two studies against each other).
"""

from __future__ import annotations

import itertools
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path

import yaml
from sqlalchemy.orm import Session, sessionmaker

from sul.analysis.clustering import ClusterAssignment, FindingRow, cluster_findings
from sul.analysis.config import ClusteringConfig
from sul.analysis.ranking import RankedCluster, rank_clusters
from sul.personas.archetypes import load_panel_config
from sul.providers.base import LLMProvider
from sul.validity.data import finding_content_key, load_provenance
from sul.validity.model import ReproducibilitySection, SeedSensitivitySection
from sul.validity.runs import run_artefact_study

DEFAULT_ARTEFACT_PATH = "artefacts/bad_onboarding.html"
DEFAULT_PANEL_PATH = "configs/panel_validity.yaml"
_ContentKey = tuple[str, str, str]


def _ranked_clusters(
    rows: list[FindingRow], config: ClusteringConfig
) -> list[RankedCluster]:
    if not rows:
        return []
    assignments: list[ClusterAssignment] = cluster_findings(rows, config)
    rows_by_id = {r.finding_id: r for r in rows}
    segment_denominators: dict[str, int] = defaultdict(int)
    for _persona_id, segment in {(r.persona_id, r.segment) for r in rows}:
        segment_denominators[segment] += 1
    total_denominator = len({r.persona_id for r in rows})
    return rank_clusters(
        rows_by_id,
        assignments,
        segment_denominators=dict(segment_denominators),
        total_denominator=total_denominator,
    )


def top5_content_key_sets(
    rows: list[FindingRow], config: ClusteringConfig
) -> list[frozenset[_ContentKey]]:
    """The content-keyed membership of the top-5 ranked clusters, in rank
    order. Exposed (not `_`-prefixed) because the negative-control tests
    exercise it directly against hand-built fixtures.
    """
    ranked = _ranked_clusters(rows, config)
    rows_by_id = {r.finding_id: r for r in rows}
    return [
        frozenset(finding_content_key(rows_by_id[fid]) for fid in rc.finding_ids)
        for rc in ranked[:5]
    ]


def jaccard(a: frozenset[_ContentKey], b: frozenset[_ContentKey]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def mean_top5_jaccard(all_top5: list[list[frozenset[_ContentKey]]]) -> float:
    """Mean pairwise, position-matched Jaccard overlap across every pair of
    repeats' top-5 cluster lists. A repeat with fewer than 5 clusters
    contributes only as many rank positions as it has.
    """
    pair_scores: list[float] = []
    for a_sets, b_sets in itertools.combinations(all_top5, 2):
        n = min(len(a_sets), len(b_sets))
        pair_scores.extend(jaccard(a_sets[i], b_sets[i]) for i in range(n))
    if not pair_scores:
        return 1.0
    return sum(pair_scores) / len(pair_scores)


def _write_panel_with_seed(base_panel_path: Path, seed: int, tmp_dir: Path) -> Path:
    """A scratch copy of `base_panel_path`'s `PanelConfig` with `seed`
    overridden. `materialize_study` only accepts a panel config *path*
    (`StudyRunConfig.panel_config_path: str`), not an object -- this is the
    minimal way to vary the seed without editing a checked-in fixture file
    per seed value.
    """
    panel_config = load_panel_config(base_panel_path)
    varied = panel_config.model_copy(update={"seed": seed})
    out_path = tmp_dir / f"panel_seed_{seed}.yaml"
    out_path.write_text(yaml.safe_dump(varied.to_config_dict()), encoding="utf-8")
    return out_path


async def measure_reproducibility(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    repeats: int = 3,
    seed_sensitivity_seeds: int = 3,
    artefact_path: str = DEFAULT_ARTEFACT_PATH,
    panel_path: str = DEFAULT_PANEL_PATH,
    clustering_config: ClusteringConfig | None = None,
    base_path: Path | None = None,
) -> ReproducibilitySection:
    """PROJECT_SPEC.md §M6.1. `repeats` >= 2 (Jaccard/variance are undefined
    over a single sample).
    """
    if repeats < 2:
        raise ValueError("reproducibility needs at least 2 repeats to compare")

    root = base_path if base_path is not None else Path.cwd()
    config = clustering_config or ClusteringConfig()

    same_seed_runs = [
        await run_artefact_study(
            session_factory,
            provider=provider,
            provider_name=provider_name,
            model=model,
            artefact_path=artefact_path,
            panel_path=panel_path,
            base_path=root,
            study_name=f"M6.1 reproducibility repeat {i}",
        )
        for i in range(repeats)
    ]
    same_seed_rows = [r.rows for r in same_seed_runs]
    finding_count_variance = statistics.pvariance(len(r) for r in same_seed_rows)
    same_seed_top5 = [top5_content_key_sets(r, config) for r in same_seed_rows]

    seed_sensitivity = await _measure_seed_sensitivity(
        session_factory,
        provider=provider,
        provider_name=provider_name,
        model=model,
        seeds=seed_sensitivity_seeds,
        artefact_path=artefact_path,
        panel_path=panel_path,
        clustering_config=config,
        base_path=root,
    )

    with session_factory() as session:
        provenance = load_provenance(
            session, study_ids=[r.study_id for r in same_seed_runs]
        )

    return ReproducibilitySection(
        repeats=repeats,
        finding_count_variance=finding_count_variance,
        mean_top5_cluster_jaccard=mean_top5_jaccard(same_seed_top5),
        seed_sensitivity=seed_sensitivity,
        provenance=provenance,
    )


async def _measure_seed_sensitivity(
    session_factory: sessionmaker[Session],
    *,
    provider: LLMProvider,
    provider_name: str,
    model: str,
    seeds: int,
    artefact_path: str,
    panel_path: str,
    clustering_config: ClusteringConfig,
    base_path: Path,
) -> SeedSensitivitySection:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        base_panel_path = base_path / panel_path
        rows_per_seed = []
        for i in range(seeds):
            seeded_panel_path = _write_panel_with_seed(
                base_panel_path, 9000 + i, tmp_dir
            )
            run = await run_artefact_study(
                session_factory,
                provider=provider,
                provider_name=provider_name,
                model=model,
                artefact_path=artefact_path,
                panel_path=str(seeded_panel_path),
                # `seeded_panel_path` is already absolute; `base_path /
                # <absolute path>` still resolves to the absolute path
                # (pathlib's `/` drops the left side for an absolute right
                # side), while `artefact_path` still needs `base_path` to
                # resolve against the real repo root.
                base_path=base_path,
                study_name=f"M6.1 seed-sensitivity seed {9000 + i}",
            )
            rows_per_seed.append(run.rows)

    finding_counts = [len(r) for r in rows_per_seed]
    cluster_counts = [
        len(_ranked_clusters(r, clustering_config)) for r in rows_per_seed
    ]
    top5_by_seed = [top5_content_key_sets(r, clustering_config) for r in rows_per_seed]

    return SeedSensitivitySection(
        seeds_tried=seeds,
        finding_count_range=(min(finding_counts), max(finding_counts)),
        cluster_count_range=(min(cluster_counts), max(cluster_counts)),
        mean_top5_cluster_jaccard=mean_top5_jaccard(top5_by_seed),
    )


__all__ = [
    "DEFAULT_ARTEFACT_PATH",
    "DEFAULT_PANEL_PATH",
    "jaccard",
    "mean_top5_jaccard",
    "measure_reproducibility",
    "top5_content_key_sets",
]
