"""PROJECT_SPEC.md §M6: per-row provenance (Task B in the M6 design
conversation). `load_provenance` reads the `ModelCall` audit trail directly
-- proven here against hand-written `ModelCall` rows with genuinely
different `(provider, agent, model)` triples, not against a single-provider
fixture where every row would trivially agree.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from sul import models
from sul.enums import AgentRole, ArtefactKind, RunStatus
from sul.validity.data import load_provenance
from sul.validity.model import AgentProvenance


def _seed_study_with_mixed_model_calls(session: Session) -> int:
    artefact = models.Artefact(
        name="a.html", kind=ArtefactKind.HTML, content_hash="prov-h1", body="<html/>"
    )
    session.add(artefact)
    session.flush()
    study = models.Study(
        name="provenance test study",
        research_goal="goal",
        artefact_id=artefact.id,
        config_hash="c1",
        git_sha="f" * 40,
    )
    session.add(study)
    session.flush()
    scenario = models.Scenario(study_id=study.id, task="task", questions=[])
    panel = models.Panel(study_id=study.id, seed=1, size=1, config_yaml="")
    session.add_all([scenario, panel])
    session.flush()
    persona = models.Persona(
        panel_id=panel.id, name="P1", segment="seg", attributes={}, card_text="card"
    )
    session.add(persona)
    session.flush()
    run = models.Run(
        study_id=study.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status=RunStatus.COMPLETED,
    )
    session.add(run)
    session.flush()

    def _call(agent: AgentRole, provider: str, model: str) -> None:
        session.add(
            models.ModelCall(
                run_id=run.id,
                agent=agent,
                provider=provider,
                model=model,
                prompt_hash="h",
                tokens_in=1,
                tokens_out=1,
                cost_usd=0.0,
                latency_ms=1,
                seed=1,
                cached=False,
            )
        )

    # A deliberately mixed configuration: the Analyst on a different model
    # from persona/moderator -- exactly the split PROJECT_SPEC.md's M6
    # design conversation asks for (Sonnet-Analyst, Haiku elsewhere).
    _call(AgentRole.PERSONA, "anthropic", "claude-haiku-4-5")
    _call(AgentRole.MODERATOR, "anthropic", "claude-haiku-4-5")
    _call(AgentRole.ANALYST, "anthropic", "claude-sonnet-5")
    session.commit()
    return study.id


def test_load_provenance_reflects_real_mixed_model_calls(session: Session) -> None:
    study_id = _seed_study_with_mixed_model_calls(session)

    provenance = load_provenance(session, study_ids=[study_id])

    assert (
        AgentProvenance(agent="persona", provider="anthropic", model="claude-haiku-4-5")
        in provenance
    )
    assert (
        AgentProvenance(
            agent="moderator", provider="anthropic", model="claude-haiku-4-5"
        )
        in provenance
    )
    assert (
        AgentProvenance(agent="analyst", provider="anthropic", model="claude-sonnet-5")
        in provenance
    )
    assert len(provenance) == 3


def test_load_provenance_is_empty_for_no_study_ids(session: Session) -> None:
    assert load_provenance(session, study_ids=[]) == []


def test_load_provenance_dedupes_repeated_identical_calls(session: Session) -> None:
    """Three persona `ModelCall` rows with the same (provider, agent, model)
    must collapse to one provenance entry -- provenance describes which
    configuration ran, not how many calls it took.
    """
    study_id = _seed_study_with_mixed_model_calls(session)
    with_dupe_session = session
    # Add a second, identical persona call to the same study.
    run = (
        with_dupe_session.query(models.Run)
        .filter(models.Run.study_id == study_id)
        .one()
    )
    with_dupe_session.add(
        models.ModelCall(
            run_id=run.id,
            agent=AgentRole.PERSONA,
            provider="anthropic",
            model="claude-haiku-4-5",
            prompt_hash="h2",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            latency_ms=1,
            seed=2,
            cached=False,
        )
    )
    with_dupe_session.commit()

    provenance = load_provenance(with_dupe_session, study_ids=[study_id])
    assert len(provenance) == 3  # still 3, not 4
