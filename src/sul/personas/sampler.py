"""Expands a `PanelConfig` into a deterministic, seeded population of personas.

Two determinism properties the spec's acceptance criteria (§M3) require, and
how each is bought:

- **Byte-identical output under a repeated seed (A1).** Every random draw is
  seeded from `sul.hashing.config_hash` (JSON, `sort_keys=True`) rather than
  Python's salted `hash()` or set/dict iteration order, so nothing here can
  vary across processes or `PYTHONHASHSEED`. `canonical_dump` gives A1's test
  a single string to compare.
- **Seed changes personas but not segment proportions (A2/A3).** Segment
  *counts* are apportioned from `SegmentSpec.weight` by the largest-remainder
  method (`_apportion_counts`) — a deterministic function of the weights and
  `size` alone, with no RNG in it at all. The seed can only ever change which
  attribute values and card text a given persona index gets, never how many
  personas land in which segment. Ties in the remainder are broken by segment
  index, not by dict/set order, so apportionment does not depend on Python's
  iteration order either.

A third property the spec doesn't name but M4/M6 depend on: **one attribute's
draw cannot perturb another's.** `_attribute_rng` seeds a fresh
`random.Random` per `(panel seed, persona index, attribute key)` rather than
pulling sequential draws off one shared stream in document order. Inserting,
removing, or reordering an attribute in the YAML therefore cannot reshuffle
any other attribute's realised value for any persona — see
`tests/test_persona_sampler.py::test_attribute_insertion_does_not_reshuffle_other_attributes`.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter

from pydantic import BaseModel, ConfigDict

from sul.hashing import config_hash
from sul.personas.archetypes import AttributeSpec, AttrValue, PanelConfig, SegmentSpec
from sul.personas.cards import CARD_TEMPLATE_VERSION, render_card

_DEFAULT_TOLERANCE_FLOOR = 0.05


class SampledPersona(BaseModel):
    """One realised persona: a segment's attributes drawn for one panel slot."""

    model_config = ConfigDict(frozen=True)

    index: int
    name: str
    segment: str
    attributes: dict[str, AttrValue | list[AttrValue]]
    card_text: str


class SampledPanel(BaseModel):
    """The full output of `sample_panel`: every persona plus the metadata
    needed to reproduce them (`sul.personas.persistence.persist_panel` stores
    this metadata, not the raw source YAML, on `Panel.config_yaml`)."""

    model_config = ConfigDict(frozen=True)

    seed: int
    size: int
    card_template_version: str
    personas: list[SampledPersona]


def _apportion_counts(segments: list[SegmentSpec], size: int) -> list[int]:
    """Deterministically split `size` slots across `segments` by weight,
    using the largest-remainder method. No randomness: this is what makes
    A3 (proportions stable under a seed change) exact rather than
    probabilistic, and it's how a quota panel is actually recruited.
    """
    total_weight = sum(s.weight for s in segments)
    quotas = [s.weight / total_weight * size for s in segments]
    floors = [math.floor(q) for q in quotas]
    remainder = size - sum(floors)
    # Break ties on fractional remainder by ascending segment index, never by
    # dict/set iteration order, so the split is reproducible regardless of
    # how segments happen to be ordered in memory.
    order = sorted(range(len(segments)), key=lambda i: (-(quotas[i] - floors[i]), i))
    counts = list(floors)
    for i in order[:remainder]:
        counts[i] += 1
    return counts


def _attribute_rng(seed: int, persona_index: int, attribute_key: str) -> random.Random:
    """A substream seeded by (panel seed, persona index, attribute key) —
    never sequential draws off one shared stream. See the module docstring.
    """
    digest = config_hash(
        {"seed": seed, "index": persona_index, "attribute": attribute_key}
    )
    return random.Random(digest)


def _draw_attribute(
    spec: AttributeSpec, rng: random.Random
) -> AttrValue | list[AttrValue]:
    if spec.choice is not None:
        return rng.choice(spec.choice)
    if spec.all_ is not None:
        return list(spec.all_)
    if spec.sample is not None:
        return rng.sample(spec.sample.from_, spec.sample.k)
    if spec.scalar is not None:
        return spec.scalar
    raise AssertionError(  # pragma: no cover - AttributeSpec._coerce guarantees this
        "AttributeSpec must set exactly one of choice/all/sample/scalar"
    )


def sample_panel(config: PanelConfig) -> SampledPanel:
    """Expand `config` into `config.size` personas, seeded deterministically."""
    counts = _apportion_counts(config.segments, config.size)
    width = max(2, len(str(max(config.size - 1, 0))))

    personas: list[SampledPersona] = []
    index = 0
    for segment, count in zip(config.segments, counts, strict=True):
        for _ in range(count):
            attributes: dict[str, AttrValue | list[AttrValue]] = {}
            for key, spec in segment.attributes.items():
                rng = _attribute_rng(config.seed, index, key)
                attributes[key] = _draw_attribute(spec, rng)

            name = f"P{index:0{width}d}_{segment.name}"
            draft = SampledPersona(
                index=index,
                name=name,
                segment=segment.name,
                attributes=attributes,
                card_text="",
            )
            card_text = render_card(draft)
            personas.append(draft.model_copy(update={"card_text": card_text}))
            index += 1

    return SampledPanel(
        seed=config.seed,
        size=config.size,
        card_template_version=CARD_TEMPLATE_VERSION,
        personas=personas,
    )


def canonical_dump(sampled: SampledPanel) -> str:
    """A stable, order-independent string representation of `sampled`, for
    A1's "byte-identical output" check. `sort_keys=True` and compact
    separators, matching `sul.hashing.config_hash`'s convention.
    """
    payload = sampled.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def segment_proportions(sampled: SampledPanel) -> dict[str, float]:
    """Realised fraction of `sampled.personas` in each segment."""
    counts = Counter(p.segment for p in sampled.personas)
    return {segment: n / sampled.size for segment, n in counts.items()}


def validate_proportions(
    config: PanelConfig, sampled: SampledPanel, *, tolerance: float | None = None
) -> None:
    """Raise `ValueError` if any segment's realised proportion in `sampled`
    strays from its target weight by more than `tolerance` (default: one
    persona's worth of rounding, or 5 points, whichever is larger).
    """
    tol = (
        tolerance
        if tolerance is not None
        else max(1 / sampled.size, _DEFAULT_TOLERANCE_FLOOR)
    )
    total_weight = sum(s.weight for s in config.segments)
    targets = {s.name: s.weight / total_weight for s in config.segments}
    realised = segment_proportions(sampled)

    for name, target in targets.items():
        actual = realised.get(name, 0.0)
        if abs(actual - target) > tol:
            raise ValueError(
                f"segment {name!r} realised proportion {actual:.4f} is "
                f"outside tolerance {tol:.4f} of target {target:.4f}"
            )


__all__ = [
    "SampledPanel",
    "SampledPersona",
    "canonical_dump",
    "sample_panel",
    "segment_proportions",
    "validate_proportions",
]
