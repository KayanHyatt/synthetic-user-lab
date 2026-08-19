"""Panel config schemas: the population definition a study samples from.

`configs/panel.example.yaml` is a `PanelConfig` document. Its shape deviates
from the spec's illustrative YAML in one respect, documented in the M3
implementation note in `PROJECT_SPEC.md`: an attribute value must be either a
bare scalar (`patience: low`) or one of three explicit wrappers —
`choice: [...]` (pick one), `all: [...]` (hold all), `sample: {from: [...],
k: N}` (pick N) — never a bare list. A bare list is ambiguous between "pick
one" and "hold all" (the spec's own example uses a bare list both ways), and
picking a default silently produces a plausible-looking persona from a config
typo, which nothing downstream would ever flag.

`extra="forbid"` runs at every level (top-level config, segment, attribute
spec) so a stray key — including a research-goal-shaped one — is a load-time
error, not a silently-ignored field. A `PanelConfig` has no field that could
carry a research goal in the first place: goals live on `Study`, not here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

AttrValue = str | int | float | bool

_WRAPPER_KEYS = ("choice", "all", "sample")


class SampleInner(BaseModel):
    """The body of a `sample: {from: [...], k: N}` attribute wrapper."""

    model_config = ConfigDict(extra="forbid")

    from_: list[AttrValue] = Field(alias="from", min_length=1)
    k: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_k_within_pool(self) -> SampleInner:
        if self.k > len(self.from_):
            raise ValueError(
                f"sample k={self.k} exceeds pool size {len(self.from_)} in "
                f"'from': {self.from_!r}"
            )
        return self


class AttributeSpec(BaseModel):
    """One persona attribute's value spec: exactly one of `choice`, `all`,
    `sample`, or a bare scalar. Never accepts a per-option weight — target
    proportions are declared exactly once, on `SegmentSpec.weight`; a second
    place to say the same thing (a weighted `choice`) would drift from it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    choice: list[AttrValue] | None = Field(default=None, min_length=1)
    all_: list[AttrValue] | None = Field(default=None, alias="all", min_length=1)
    sample: SampleInner | None = None
    scalar: AttrValue | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: object) -> object:
        if isinstance(data, Mapping):
            keys = set(data.keys())
            unknown = keys - set(_WRAPPER_KEYS)
            if unknown:
                raise ValueError(
                    f"unknown attribute-spec key(s) {sorted(unknown)!r}; use "
                    f"one of {_WRAPPER_KEYS!r}"
                )
            if len(keys) != 1:
                raise ValueError(
                    "attribute spec must set exactly one of "
                    f"{_WRAPPER_KEYS!r}, got {sorted(keys)!r}"
                )
            return dict(data)
        if isinstance(data, list):
            raise ValueError(
                "a bare list is not a valid attribute value (ambiguous "
                "between 'pick one' and 'hold all'); wrap it in "
                "'choice: [...]' (pick one), 'all: [...]' (hold all), or "
                "'sample: {from: [...], k: N}' (pick N) — a bare scalar "
                "(e.g. 'patience: low') is fine as-is"
            )
        if data is None:
            raise ValueError("attribute value cannot be null")
        return {"scalar": data}

    def to_config_value(self) -> object:
        """Serialise back to the wrapper syntax a panel YAML would use."""
        if self.choice is not None:
            return {"choice": list(self.choice)}
        if self.all_ is not None:
            return {"all": list(self.all_)}
        if self.sample is not None:
            return {"sample": {"from": list(self.sample.from_), "k": self.sample.k}}
        if self.scalar is not None:
            return self.scalar
        raise AssertionError(  # pragma: no cover - _coerce guarantees this
            "AttributeSpec must set exactly one of choice/all/sample/scalar"
        )


class SegmentSpec(BaseModel):
    """One archetype: a name, a target population weight, and its attributes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float = Field(gt=0)
    attributes: dict[str, AttributeSpec] = Field(default_factory=dict)

    def to_config_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "weight": self.weight,
            "attributes": {k: v.to_config_value() for k, v in self.attributes.items()},
        }


class PanelConfig(BaseModel):
    """A persona population definition: `configs/panel.example.yaml`'s shape.

    Deliberately has no field that could carry a research goal, a scenario,
    or a study reference — see the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    seed: int
    size: int = Field(gt=0)
    segments: list[SegmentSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_segments(self) -> PanelConfig:
        names = [s.name for s in self.segments]
        if len(names) != len(set(names)):
            raise ValueError(f"segment names must be unique, got {names!r}")
        total_weight = sum(s.weight for s in self.segments)
        if total_weight <= 0:
            raise ValueError("segment weights must sum to a positive number")
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(
                f"segment weights must sum to 1.0, got {total_weight!r} "
                f"across segments {names!r}"
            )
        return self

    def to_config_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "size": self.size,
            "segments": [s.to_config_dict() for s in self.segments],
        }


class ResolvedPanelConfig(PanelConfig):
    """A `PanelConfig` plus the card template version it was sampled with.

    This, not `PanelConfig`, is what gets serialised into `Panel.config_yaml`
    (`sul.personas.persistence`) — the extra field records what produced
    `card_text` without requiring a `ModelCall` row to hang it on, since M3
    makes none. `PanelConfig` itself stays free of this field so a
    user-authored panel YAML (which never mentions a template version) still
    validates against it directly.
    """

    card_template_version: str

    def to_config_dict(self) -> dict[str, object]:
        base = super().to_config_dict()
        base["card_template_version"] = self.card_template_version
        return base


def parse_panel_config(text: str) -> PanelConfig:
    """Parse a YAML document's text into a `PanelConfig`."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("panel config must be a YAML mapping")
    return PanelConfig.model_validate(raw)


def parse_resolved_panel_config(text: str) -> ResolvedPanelConfig:
    """Parse a `Panel.config_yaml` document's text into a `ResolvedPanelConfig`."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("resolved panel config must be a YAML mapping")
    return ResolvedPanelConfig.model_validate(raw)


def load_panel_config(path: str | Path) -> PanelConfig:
    """Load and parse a panel config YAML file, e.g. `configs/panel.example.yaml`."""
    return parse_panel_config(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "AttrValue",
    "AttributeSpec",
    "PanelConfig",
    "ResolvedPanelConfig",
    "SampleInner",
    "SegmentSpec",
    "load_panel_config",
    "parse_panel_config",
    "parse_resolved_panel_config",
]
