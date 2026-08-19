"""Sample -> persist -> rebuild-from-stored-config round trip.

This is M6's reproducibility criterion bought early: if `rebuild_sampled_panel`
(which reads only `Panel.seed` and `Panel.config_yaml`, never the original
source file) doesn't reproduce exactly what was persisted, a regression in
seed derivation would otherwise only surface once M6 runs. It's also the test
that actually catches a positional (rather than keyed) RNG substream bug --
that bug survives a same-process double-call but not a rebuild from stored
config alone.

Also verifies the structural guarantee from the M3 plan: `Panel.config_yaml`
cannot contain a research goal, because it is built from an already-validated
`PanelConfig` (`extra="forbid"` at every level), never from raw source text.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import ArtefactKind
from sul.personas.archetypes import PanelConfig
from sul.personas.persistence import persist_panel, rebuild_sampled_panel
from sul.personas.sampler import sample_panel

_CONFIG_PAYLOAD = {
    "seed": 123,
    "size": 9,
    "segments": [
        {
            "name": "time_poor_professional",
            "weight": 0.6,
            "attributes": {
                "tech_comfort": {"choice": ["high", "medium", "low"]},
                "goals": {"all": ["evaluate quickly"]},
            },
        },
        {
            "name": "cost_sensitive_student",
            "weight": 0.4,
            "attributes": {
                "constraints": {"sample": {"from": ["a", "b", "c"], "k": 2}},
            },
        },
    ],
}


def _make_study(session: Session, *, research_goal: str) -> models.Study:
    artefact = models.Artefact(
        name="a.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
    )
    session.add(artefact)
    session.flush()

    study = models.Study(
        name="persistence round-trip study",
        research_goal=research_goal,
        artefact_id=artefact.id,
        config_hash="c1",
        git_sha="f" * 40,
    )
    session.add(study)
    session.flush()
    return study


def test_persist_then_rebuild_round_trip(
    session_factory: sessionmaker[Session],
) -> None:
    config = PanelConfig.model_validate(_CONFIG_PAYLOAD)
    sampled = sample_panel(config)

    with session_factory() as session:
        study = _make_study(session, research_goal="goal")
        panel_row = persist_panel(
            session, study_id=study.id, config=config, sampled=sampled
        )
        session.commit()
        panel_id = panel_row.id

    with session_factory() as session:
        reloaded_panel = session.get(models.Panel, panel_id)
        assert reloaded_panel is not None

        persisted_personas = (
            session.query(models.Persona)
            .filter_by(panel_id=reloaded_panel.id)
            .order_by(models.Persona.id)
            .all()
        )

        rebuilt = rebuild_sampled_panel(reloaded_panel)

    assert len(persisted_personas) == len(rebuilt.personas) == config.size

    for persisted, rebuilt_persona in zip(
        persisted_personas, rebuilt.personas, strict=True
    ):
        assert persisted.name == rebuilt_persona.name
        assert persisted.segment == rebuilt_persona.segment
        assert persisted.attributes == rebuilt_persona.attributes
        assert persisted.card_text == rebuilt_persona.card_text


def test_config_yaml_never_contains_the_research_goal(
    session_factory: sessionmaker[Session],
) -> None:
    goal_sentinel = "ZZGOALZZ-do-not-leak-into-panel-config"
    config = PanelConfig.model_validate(_CONFIG_PAYLOAD)
    sampled = sample_panel(config)

    with session_factory() as session:
        study = _make_study(session, research_goal=goal_sentinel)
        panel_row = persist_panel(
            session, study_id=study.id, config=config, sampled=sampled
        )
        session.commit()
        config_yaml = panel_row.config_yaml

    assert goal_sentinel not in config_yaml
