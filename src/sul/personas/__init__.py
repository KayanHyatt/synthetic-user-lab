"""Persona system: panel config -> seeded sampler -> persona cards (spec §M3).

Pure, offline, deterministic: `(PanelConfig, seed) -> SampledPanel`. No agent,
no provider, no `ModelCall` lives in this package — those are §M4's
orchestrator, which reads `Persona.card_text` and nothing else about how it
was produced. See the M3 implementation note in `PROJECT_SPEC.md` for the
isolation reasoning and the ambiguities this package resolves.
"""

from __future__ import annotations

from sul.personas.archetypes import (
    AttributeSpec,
    PanelConfig,
    ResolvedPanelConfig,
    SegmentSpec,
    load_panel_config,
    parse_panel_config,
    parse_resolved_panel_config,
)
from sul.personas.cards import CARD_TEMPLATE_VERSION, render_card
from sul.personas.persistence import (
    persist_panel,
    rebuild_config_from_panel,
    rebuild_sampled_panel,
)
from sul.personas.sampler import (
    SampledPanel,
    SampledPersona,
    canonical_dump,
    sample_panel,
    segment_proportions,
    validate_proportions,
)

__all__ = [
    "CARD_TEMPLATE_VERSION",
    "AttributeSpec",
    "PanelConfig",
    "ResolvedPanelConfig",
    "SampledPanel",
    "SampledPersona",
    "SegmentSpec",
    "canonical_dump",
    "load_panel_config",
    "parse_panel_config",
    "parse_resolved_panel_config",
    "persist_panel",
    "rebuild_config_from_panel",
    "rebuild_sampled_panel",
    "render_card",
    "sample_panel",
    "segment_proportions",
    "validate_proportions",
]
