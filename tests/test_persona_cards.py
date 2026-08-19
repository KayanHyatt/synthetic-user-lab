"""Persona card rendering: the behavioural floor (spec §M3 B4) and the
card-level isolation boundary this milestone can enforce (spec §M3's only
persona-bound string is the card; the moderator/analyst isolation tests are
§M4's, per the M3 implementation note in PROJECT_SPEC.md).

Sentinels are distinctive strings (`ZZ...ZZ`), not ordinary domain words like
"usability", so a substring match can't pass by luck.
"""

from __future__ import annotations

import inspect

from sul.personas.archetypes import PanelConfig
from sul.personas.cards import render_card
from sul.personas.sampler import SampledPersona, sample_panel


def test_render_card_signature_has_no_goal_shaped_parameter() -> None:
    """Proof, not convention: `render_card` cannot be handed a goal because
    no parameter exists for one to arrive through.
    """
    params = set(inspect.signature(render_card).parameters)
    assert params == {"persona"}


def test_card_includes_own_attributes_and_behavioural_floor() -> None:
    persona = SampledPersona(
        index=0,
        name="P00_time_poor_professional",
        segment="time_poor_professional",
        attributes={
            "tech_comfort": "ZZATTR-TECHCOMFORTZZ",
            "goals": ["ZZATTR-GOAL-ONEZZ", "ZZATTR-GOAL-TWOZZ"],
        },
        card_text="",
    )
    card = render_card(persona)

    # Own attributes present.
    assert "ZZATTR-TECHCOMFORTZZ" in card
    assert "ZZATTR-GOAL-ONEZZ" in card
    assert "ZZATTR-GOAL-TWOZZ" in card
    assert "time poor professional" in card  # humanized segment

    # Behavioural floor (B4): user, not reviewer; act, get confused, give up
    # and say so.
    assert "not a reviewer" in card
    assert "got stuck or gave up" in card
    assert "Never mention that you are an AI" in card


def test_card_never_leaks_sibling_persona_or_goal_sentinels() -> None:
    config = PanelConfig.model_validate(
        {
            "seed": 99,
            "size": 2,
            "segments": [
                {
                    "name": "segment_a",
                    "weight": 0.5,
                    "attributes": {"trait": "ZZPERSONA-A-SENTINELZZ"},
                },
                {
                    "name": "segment_b",
                    "weight": 0.5,
                    "attributes": {"trait": "ZZPERSONA-B-SENTINELZZ"},
                },
            ],
        }
    )
    sampled = sample_panel(config)
    persona_a, persona_b = sampled.personas
    assert persona_a.segment == "segment_a"
    assert persona_b.segment == "segment_b"

    card_a = persona_a.card_text
    card_b = persona_b.card_text

    # Each card carries only its own persona's sentinel.
    assert "ZZPERSONA-A-SENTINELZZ" in card_a
    assert "ZZPERSONA-B-SENTINELZZ" not in card_a
    assert persona_b.name not in card_a

    assert "ZZPERSONA-B-SENTINELZZ" in card_b
    assert "ZZPERSONA-A-SENTINELZZ" not in card_b
    assert persona_a.name not in card_b

    # A goal was never given to render_card at all -- there is no channel
    # for a sentinel to have arrived through in the first place.
    goal_sentinel = "ZZGOALZZ-do-not-leak-to-personas"
    assert goal_sentinel not in card_a
    assert goal_sentinel not in card_b
