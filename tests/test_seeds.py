"""`sul.runner.seeds.derive_seed`: a pure function, not a shared stream.

Golden values pin the derivation itself -- any change to it is a visible
diff here, not a silent drift. The collision test guards against the one
collision `FakeProvider`'s key genuinely could produce if `AgentRole` were
ever dropped from the derivation (see the M4 implementation note in
PROJECT_SPEC.md on why the "schema not in the key" premise in the milestone
prompt doesn't hold against this codebase's `FakeProvider`).
"""

from __future__ import annotations

from sul.enums import AgentRole
from sul.runner.seeds import derive_seed


def test_derive_seed_golden_values() -> None:
    """Pinned values: a change here means the derivation changed, which must
    be a deliberate, reviewed edit -- not an accidental refactor.
    """
    assert (
        derive_seed(
            panel_seed=42,
            persona_key="P00_time_poor_professional",
            agent=AgentRole.PERSONA,
            turn_index=1,
        )
        == 2776782112109055381
    )
    assert (
        derive_seed(
            panel_seed=42,
            persona_key="P00_time_poor_professional",
            agent=AgentRole.MODERATOR,
            turn_index=2,
        )
        == 2488787099276268369
    )
    assert (
        derive_seed(
            panel_seed=1, persona_key="P00_x", agent=AgentRole.ANALYST, turn_index=0
        )
        == 490646700590523556
    )


def test_same_inputs_are_byte_identical() -> None:
    first = derive_seed(
        panel_seed=7, persona_key="P03_seg", agent=AgentRole.PERSONA, turn_index=3
    )
    second = derive_seed(
        panel_seed=7, persona_key="P03_seg", agent=AgentRole.PERSONA, turn_index=3
    )
    assert first == second


def test_persona_identity_changes_the_seed() -> None:
    base = derive_seed(
        panel_seed=1, persona_key="P00_a", agent=AgentRole.PERSONA, turn_index=1
    )
    other = derive_seed(
        panel_seed=1, persona_key="P01_a", agent=AgentRole.PERSONA, turn_index=1
    )
    assert base != other


def test_turn_index_changes_the_seed() -> None:
    base = derive_seed(
        panel_seed=1, persona_key="P00_a", agent=AgentRole.PERSONA, turn_index=1
    )
    other = derive_seed(
        panel_seed=1, persona_key="P00_a", agent=AgentRole.PERSONA, turn_index=2
    )
    assert base != other


def test_panel_seed_changes_the_seed() -> None:
    base = derive_seed(
        panel_seed=1, persona_key="P00_a", agent=AgentRole.PERSONA, turn_index=1
    )
    other = derive_seed(
        panel_seed=2, persona_key="P00_a", agent=AgentRole.PERSONA, turn_index=1
    )
    assert base != other


def test_moderator_and_persona_never_collide_at_the_same_turn_index() -> None:
    """The exact scenario the milestone prompt's (mistaken, see module
    docstring) premise describes: same persona, same turn index, different
    agent. `AgentRole` is part of the key precisely so this cannot collide.
    """
    persona_seed = derive_seed(
        panel_seed=42, persona_key="P05_seg", agent=AgentRole.PERSONA, turn_index=3
    )
    moderator_seed = derive_seed(
        panel_seed=42, persona_key="P05_seg", agent=AgentRole.MODERATOR, turn_index=3
    )
    assert persona_seed != moderator_seed


def test_seed_is_within_signed_64_bit_range() -> None:
    seed = derive_seed(
        panel_seed=999999, persona_key="P39_x", agent=AgentRole.ANALYST, turn_index=50
    )
    assert 0 <= seed < (1 << 63)
