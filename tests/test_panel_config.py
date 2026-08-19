"""Panel config loading and validation (spec §M3).

Covers: the spec-named example file loads; the wrapper syntax (§4.1 of the
M3 plan) is enforced — a bare list is a load-time error naming all three
wrappers, never a defaulted meaning; weights are declared exactly once, on
`SegmentSpec.weight`, and must sum to 1.0; and `extra="forbid"` at every
level makes a research-goal-shaped key a load-time error rather than a
silently-ignored one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from sul.personas.archetypes import PanelConfig, parse_panel_config

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PANEL = REPO_ROOT / "configs" / "panel.example.yaml"


def _minimal_config(**segment_overrides: object) -> dict[str, object]:
    segment: dict[str, object] = {
        "name": "seg_a",
        "weight": 1.0,
        "attributes": {"patience": "low"},
    }
    segment.update(segment_overrides)
    return {"seed": 1, "size": 4, "segments": [segment]}


def test_example_panel_config_loads() -> None:
    config = PanelConfig.model_validate(
        yaml.safe_load(EXAMPLE_PANEL.read_text(encoding="utf-8"))
    )
    assert config.seed == 42
    assert config.size == 40
    names = [s.name for s in config.segments]
    assert names == [
        "time_poor_professional",
        "cost_sensitive_student",
        "skeptical_evaluator",
    ]
    assert sum(s.weight for s in config.segments) == pytest.approx(1.0)


def test_bare_scalar_is_legal() -> None:
    config = PanelConfig.model_validate(_minimal_config())
    spec = config.segments[0].attributes["patience"]
    assert spec.scalar == "low"


def test_bare_list_is_rejected_with_message_naming_wrappers() -> None:
    payload = _minimal_config(
        attributes={"goals": ["evaluate quickly", "avoid setup work"]}
    )
    with pytest.raises(ValidationError) as exc_info:
        PanelConfig.model_validate(payload)
    message = str(exc_info.value)
    assert "choice" in message
    assert "all" in message
    assert "sample" in message


def test_choice_wrapper_parses() -> None:
    payload = _minimal_config(attributes={"tech_comfort": {"choice": ["high", "low"]}})
    config = PanelConfig.model_validate(payload)
    spec = config.segments[0].attributes["tech_comfort"]
    assert spec.choice == ["high", "low"]


def test_all_wrapper_parses() -> None:
    payload = _minimal_config(attributes={"goals": {"all": ["a", "b"]}})
    config = PanelConfig.model_validate(payload)
    spec = config.segments[0].attributes["goals"]
    assert spec.all_ == ["a", "b"]


def test_sample_wrapper_parses() -> None:
    payload = _minimal_config(
        attributes={"constraints": {"sample": {"from": ["a", "b", "c"], "k": 2}}}
    )
    config = PanelConfig.model_validate(payload)
    spec = config.segments[0].attributes["constraints"]
    assert spec.sample is not None
    assert spec.sample.from_ == ["a", "b", "c"]
    assert spec.sample.k == 2


def test_sample_wrapper_rejects_k_larger_than_pool() -> None:
    payload = _minimal_config(
        attributes={"constraints": {"sample": {"from": ["a", "b"], "k": 3}}}
    )
    with pytest.raises(ValidationError, match="exceeds pool size"):
        PanelConfig.model_validate(payload)


def test_unknown_wrapper_key_is_rejected() -> None:
    payload = _minimal_config(attributes={"tech_comfort": {"pick": ["high", "low"]}})
    with pytest.raises(ValidationError, match="unknown attribute-spec key"):
        PanelConfig.model_validate(payload)


def test_multiple_wrapper_keys_are_rejected() -> None:
    payload = _minimal_config(
        attributes={"tech_comfort": {"choice": ["high"], "all": ["low"]}}
    )
    with pytest.raises(ValidationError, match="exactly one of"):
        PanelConfig.model_validate(payload)


def test_choice_wrapper_rejects_per_option_weight() -> None:
    """Weights are declared exactly once (SegmentSpec.weight); an attribute
    wrapper that also accepted a weight would be a second place to say the
    same thing, free to drift from it.
    """
    payload = _minimal_config(
        attributes={"tech_comfort": {"choice": ["high", "low"], "weight": 0.5}}
    )
    with pytest.raises(ValidationError):
        PanelConfig.model_validate(payload)


def test_weight_sum_must_equal_one() -> None:
    payload = {
        "seed": 1,
        "size": 4,
        "segments": [
            {"name": "a", "weight": 0.5, "attributes": {}},
            {"name": "b", "weight": 0.6, "attributes": {}},
        ],
    }
    with pytest.raises(ValidationError, match="sum to 1.0"):
        PanelConfig.model_validate(payload)


def test_duplicate_segment_names_are_rejected() -> None:
    payload = {
        "seed": 1,
        "size": 4,
        "segments": [
            {"name": "a", "weight": 0.5, "attributes": {}},
            {"name": "a", "weight": 0.5, "attributes": {}},
        ],
    }
    with pytest.raises(ValidationError, match="unique"):
        PanelConfig.model_validate(payload)


def test_top_level_goal_sentinel_is_rejected() -> None:
    """A research goal has no field to ride in on; extra='forbid' makes a
    stray key naming one a load-time error, not a silently-ignored field.
    """
    payload = _minimal_config()
    payload["research_goal"] = "ZZGOALZZ-do-not-leak"
    with pytest.raises(ValidationError):
        PanelConfig.model_validate(payload)


def test_segment_level_goal_sentinel_is_rejected() -> None:
    payload = _minimal_config()
    segments = payload["segments"]
    assert isinstance(segments, list)
    segments[0]["topic"] = "ZZGOALZZ-do-not-leak"
    with pytest.raises(ValidationError):
        PanelConfig.model_validate(payload)


def test_parse_panel_config_rejects_non_mapping_document() -> None:
    with pytest.raises(ValueError, match="mapping"):
        parse_panel_config("- just\n- a\n- list\n")
