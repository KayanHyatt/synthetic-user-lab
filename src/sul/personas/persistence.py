"""Writes a sampled panel into the `Panel` / `Persona` tables, and rebuilds
one back from only what was stored — the M6-reproducibility check bought
early: `persist_panel` then `rebuild_sampled_panel` on the same row must
yield byte-identical personas (`tests/test_persona_persistence.py`).

`Panel.config_yaml` stores a *resolved config snapshot*
(`ResolvedPanelConfig.to_config_dict()`, re-serialised from the validated
`PanelConfig` plus the card template version) — never the raw source YAML
file. This is deliberate, not incidental: a raw document could carry a
comment or a stray extra key past validation, and a resolved snapshot cannot,
because it was built from an already-validated `PanelConfig` object with
`extra="forbid"` at every level. Anything holding a `Panel` row therefore has
no research goal one lookup away, because the row cannot contain one.
"""

from __future__ import annotations

import yaml
from sqlalchemy.orm import Session

from sul import models
from sul.personas.archetypes import (
    PanelConfig,
    ResolvedPanelConfig,
    SegmentSpec,
    parse_resolved_panel_config,
)
from sul.personas.sampler import SampledPanel, sample_panel
from sul.schemas.panel import PanelCreate, PersonaCreate


def persist_panel(
    session: Session, *, study_id: int, config: PanelConfig, sampled: SampledPanel
) -> models.Panel:
    """Persist `sampled` (already produced by `sample_panel(config)`) as a
    `Panel` row plus one `Persona` row per sampled persona.
    """
    resolved = ResolvedPanelConfig(
        seed=config.seed,
        size=config.size,
        segments=config.segments,
        card_template_version=sampled.card_template_version,
    )
    # sort_keys=False: attribute order inside a segment is meaningful (it's
    # the order the card renders them in), so the dump must preserve
    # `PanelConfig`'s own insertion order rather than alphabetising it -- an
    # alphabetised round trip would still carry the same attribute *values*
    # but change every persona's `card_text` byte-for-byte, which the
    # persist -> rebuild round trip in `tests/test_persona_persistence.py`
    # checks for exactly.
    config_yaml = yaml.safe_dump(resolved.to_config_dict(), sort_keys=False)

    panel_row = PanelCreate(
        study_id=study_id, seed=config.seed, size=config.size, config_yaml=config_yaml
    ).to_orm()
    session.add(panel_row)
    session.flush()

    for persona in sampled.personas:
        session.add(
            PersonaCreate(
                panel_id=panel_row.id,
                name=persona.name,
                segment=persona.segment,
                attributes=dict(persona.attributes),
                card_text=persona.card_text,
            ).to_orm()
        )
    session.flush()

    return panel_row


def rebuild_config_from_panel(panel: models.Panel) -> PanelConfig:
    """Reconstruct the `PanelConfig` that produced `panel`, from only
    `panel.config_yaml` — never from the original source YAML file, which
    the caller may no longer have.
    """
    resolved = parse_resolved_panel_config(panel.config_yaml)
    segments: list[SegmentSpec] = resolved.segments
    return PanelConfig(seed=resolved.seed, size=resolved.size, segments=segments)


def rebuild_sampled_panel(panel: models.Panel) -> SampledPanel:
    """Re-run the sampler from only `panel.config_yaml`. Byte-identical to
    the `SampledPanel` originally passed to `persist_panel` for this row,
    by A1 (`sample_panel`'s determinism) plus the fact that `config_yaml`
    losslessly round-trips a `PanelConfig`.
    """
    return sample_panel(rebuild_config_from_panel(panel))


__all__ = ["persist_panel", "rebuild_config_from_panel", "rebuild_sampled_panel"]
