"""Persona sampler determinism (spec §M3 acceptance criteria).

- A1: same seed -> byte-identical output (`canonical_dump`).
- A2: changing only the seed changes the personas...
- A3: ...but not the segment proportions beyond tolerance.

Plus the RNG-substream independence property the spec doesn't name but M4/M6
need: inserting an unrelated attribute must not reshuffle any other
attribute's realised value for any persona.
"""

from __future__ import annotations

import yaml

from sul.personas.archetypes import PanelConfig, parse_panel_config
from sul.personas.sampler import (
    canonical_dump,
    sample_panel,
    segment_proportions,
    validate_proportions,
)


def _config(seed: int) -> PanelConfig:
    return PanelConfig.model_validate(
        {
            "seed": seed,
            "size": 20,
            "segments": [
                {
                    "name": "time_poor_professional",
                    "weight": 0.35,
                    "attributes": {
                        "tech_comfort": {"choice": ["high", "medium", "low"]},
                        "patience": "low",
                        "goals": {"all": ["evaluate quickly", "avoid setup work"]},
                    },
                },
                {
                    "name": "cost_sensitive_student",
                    "weight": 0.4,
                    "attributes": {
                        "tech_comfort": {"choice": ["medium", "low"]},
                        "constraints": {
                            "sample": {
                                "from": ["tight budget", "shared device", "mobile"],
                                "k": 2,
                            }
                        },
                    },
                },
                {
                    "name": "skeptical_evaluator",
                    "weight": 0.25,
                    "attributes": {
                        "tech_comfort": {"choice": ["high", "low"]},
                    },
                },
            ],
        }
    )


def test_sample_panel_is_byte_identical_across_calls_same_seed() -> None:
    config = _config(seed=42)
    first = sample_panel(config)
    second = sample_panel(config)
    assert canonical_dump(first) == canonical_dump(second)


def test_sample_panel_is_byte_identical_across_process_boundary() -> None:
    """Same as above, but the second config is rebuilt from re-parsed YAML
    text (the same path persistence round-trips through) rather than the
    original Python object -- catches any accidental dependence on object
    identity or in-memory state rather than the document's actual content.
    """
    config_a = _config(seed=42)
    # sort_keys=False: attribute order is meaningful (it's what a persona's
    # card renders in), matching sul.personas.persistence.persist_panel.
    config_b = parse_panel_config(
        yaml.safe_dump(config_a.to_config_dict(), sort_keys=False)
    )
    assert canonical_dump(sample_panel(config_a)) == canonical_dump(
        sample_panel(config_b)
    )


def test_seed_change_alters_personas() -> None:
    sampled_a = sample_panel(_config(seed=1))
    sampled_b = sample_panel(_config(seed=2))
    assert canonical_dump(sampled_a) != canonical_dump(sampled_b)
    # At least one attribute value actually differs -- not just card text
    # whitespace or ordering.
    attrs_a = [p.attributes for p in sampled_a.personas]
    attrs_b = [p.attributes for p in sampled_b.personas]
    assert attrs_a != attrs_b


def test_seed_change_does_not_move_segment_proportions() -> None:
    config_a = _config(seed=1)
    config_b = _config(seed=2)
    sampled_a = sample_panel(config_a)
    sampled_b = sample_panel(config_b)

    proportions_a = segment_proportions(sampled_a)
    proportions_b = segment_proportions(sampled_b)
    assert proportions_a == proportions_b  # exact: apportionment has no RNG in it

    validate_proportions(config_a, sampled_a)
    validate_proportions(config_b, sampled_b)


def test_segment_apportionment_matches_target_weights() -> None:
    config = _config(seed=42)
    sampled = sample_panel(config)
    segment_names = (
        "time_poor_professional",
        "cost_sensitive_student",
        "skeptical_evaluator",
    )
    counts = {
        segment: sum(1 for p in sampled.personas if p.segment == segment)
        for segment in segment_names
    }
    # size=20, weights .35/.4/.25 -> largest-remainder apportionment is exact
    assert counts == {
        "time_poor_professional": 7,
        "cost_sensitive_student": 8,
        "skeptical_evaluator": 5,
    }


def test_validate_proportions_raises_outside_tolerance() -> None:
    # Weights that don't divide evenly into `size` force the
    # largest-remainder apportionment to round one segment up, so realised
    # proportions cannot equal the targets exactly -- unlike `_config`
    # above, where .35/.4/.25 of 20 are already integers.
    uneven = PanelConfig.model_validate(
        {
            "seed": 1,
            "size": 10,
            "segments": [
                {"name": "a", "weight": 1 / 3, "attributes": {}},
                {"name": "b", "weight": 1 / 3, "attributes": {}},
                {"name": "c", "weight": 1 / 3, "attributes": {}},
            ],
        }
    )
    sampled = sample_panel(uneven)
    try:
        validate_proportions(uneven, sampled, tolerance=0.0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError with a zero tolerance")


def test_attribute_insertion_does_not_reshuffle_other_attributes() -> None:
    """Inserting a brand-new attribute ahead of an existing one in the YAML
    must not change any persona's value for the existing attribute -- proof
    that draws are keyed by (seed, index, attribute key), not by position in
    a shared stream.
    """
    base = PanelConfig.model_validate(
        {
            "seed": 7,
            "size": 6,
            "segments": [
                {
                    "name": "only_segment",
                    "weight": 1.0,
                    "attributes": {"x": {"choice": ["a", "b", "c", "d", "e"]}},
                }
            ],
        }
    )
    with_new_attribute = PanelConfig.model_validate(
        {
            "seed": 7,
            "size": 6,
            "segments": [
                {
                    "name": "only_segment",
                    "weight": 1.0,
                    "attributes": {
                        # "y" inserted *before* "x" in document order.
                        "y": {"choice": ["p", "q"]},
                        "x": {"choice": ["a", "b", "c", "d", "e"]},
                    },
                }
            ],
        }
    )

    before = sample_panel(base)
    after = sample_panel(with_new_attribute)

    x_before = [p.attributes["x"] for p in before.personas]
    x_after = [p.attributes["x"] for p in after.personas]
    assert x_before == x_after

    segments_before = [p.segment for p in before.personas]
    segments_after = [p.segment for p in after.personas]
    assert segments_before == segments_after


def test_canonical_dump_is_stable_json() -> None:
    sampled = sample_panel(_config(seed=42))
    dump = canonical_dump(sampled)
    assert dump == canonical_dump(sample_panel(_config(seed=42)))
    # Sanity: it really is JSON, not e.g. repr().
    import json

    parsed = json.loads(dump)
    assert parsed["seed"] == 42
    assert len(parsed["personas"]) == 20
