"""Per-call seed derivation: a pure function of (panel seed, persona identity,
agent, turn index) -- never `uuid4`, wall-clock time, a shared `random.Random`
advanced turn by turn, or dict/set iteration order (PROJECT_SPEC.md §M4
carry-forward). Same substream approach as M3's `sul.personas.sampler
._attribute_rng`: hash the whole key through `sul.hashing.config_hash`
(`json.dumps(sort_keys=True)` + sha256), never Python's salted builtin
`hash()`.

**Persona identity, not `Persona.id`.** The carry-forward's own text says
"study seed, persona id, turn index". `Persona.id` is a SQLite surrogate key
-- not reproducible across a rebuilt database, which would break the spec's
own cross-process reproducibility requirement (run the panel in one process,
rebuild the database, run it again, get byte-identical transcripts). This
module instead keys on `Persona.name`, which
`sul.personas.sampler.sample_panel` derives deterministically from
`(panel seed, persona index)` -- reproducible identity, not row identity.
Documented as a deviation in PROJECT_SPEC.md's M4 implementation note.

**"Study seed" is `Panel.seed`.** `Study` has no seed column; `Panel.seed` is
the only seed in the object graph, and it is exactly the seed
`sul.personas.sampler.sample_panel` already used to derive this persona's
identity and attributes -- reusing it here keeps one seed meaning one
reproducible run, rather than introducing a second, unrelated seed concept.
"""

from __future__ import annotations

from sul.enums import AgentRole
from sul.hashing import config_hash

# Masks the top bit off a 64-hex-digit sha256 prefix so the result always
# fits a signed 64-bit integer -- `FakeProvider` and every real provider's
# `seed` parameter are typed as plain `int`, and a full 256-bit digest would
# overflow some providers' native seed range for no benefit here.
_SEED_MASK = (1 << 63) - 1


def derive_seed(
    *, panel_seed: int, persona_key: str, agent: AgentRole, turn_index: int
) -> int:
    """Deterministically derive one call's `seed` from its full identity.

    `agent` is part of the key (not just `persona_key` + `turn_index`) so a
    moderator call and a persona call at the same turn index never derive
    the same seed -- see `tests/test_seeds.py
    ::test_moderator_and_persona_never_collide_at_the_same_turn_index`.
    """
    digest = config_hash(
        {
            "panel_seed": panel_seed,
            "persona": persona_key,
            "agent": agent.value,
            "turn": turn_index,
        }
    )
    return int(digest[:16], 16) & _SEED_MASK


__all__ = ["derive_seed"]
