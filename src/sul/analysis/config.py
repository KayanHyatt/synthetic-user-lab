"""`ClusteringConfig`: the clustering knobs named by the M5 plan (threshold,
metric, linkage, vectorizer settings), pulled into config the same way every
other tunable in this repo is (`sul.runner.config.RunnerOptions`,
`BudgetConfig`, ...) rather than left as literals inside the clustering
module -- M6 has to be able to say what settings produced a given report, and
that requires the settings to be a value it can read, not a constant it has
to grep for.

`distance_threshold` default: chosen from `tests/test_clustering.py`'s
discrimination fixture, not picked first and validated after (see that
module's docstring for the actual cosine-distance numbers). 0.6 sits with
clear margin below the near-duplicate cluster's internal spread (~0.45) and
above the closest "must stay apart" pair in that fixture (~0.65) -- but that
margin is asymmetric, and the module docstring in `clustering.py` explains
why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ClusteringConfig(BaseModel):
    """Settings for `sul.analysis.clustering.cluster_findings`.

    `extra="forbid"` per this repo's convention for every config model (M3's
    `AttributeSpec`, M4's `RunnerOptions`) -- a typo'd key should fail loudly,
    not silently no-op.
    """

    model_config = ConfigDict(extra="forbid")

    distance_threshold: float = Field(default=0.6, gt=0.0)
    metric: Literal["cosine"] = "cosine"
    linkage: Literal["average"] = "average"
    stop_words: Literal["english"] | None = "english"
    min_df: int = Field(default=1, ge=1)


def load_clustering_config(path: str | Path) -> ClusteringConfig:
    """Load and validate a `ClusteringConfig` YAML document."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("clustering config must be a YAML mapping")
    return ClusteringConfig.model_validate(raw)


__all__ = ["ClusteringConfig", "load_clustering_config"]
