"""The persona-isolation boundary, enforced in code rather than by prompt wording.

Two independent checks: (1) a `PersonaContext` built for one persona never
contains the research goal or any sentinel belonging to the study, scenario,
or a sibling persona, even after serialisation; (2) walking from a `Persona`
up to its `Study` raises immediately rather than silently lazy-loading it.
"""

from __future__ import annotations

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from sul.schemas.isolation import PersonaContext
from tests.conftest import StudyGraph


def test_persona_context_never_leaks_sentinels(study_graph: StudyGraph) -> None:
    turns = [study_graph.turn_moderator, study_graph.turn_persona]

    context = PersonaContext.build(
        persona=study_graph.persona_a,
        artefact=study_graph.artefact,
        turns=turns,
    )

    # Serialise the *whole* object, not field-by-field: a field-by-field check
    # rots the moment someone adds a field to PersonaContext without updating
    # this test. A full-payload scan does not.
    payload = context.model_dump_json()

    forbidden = [
        study_graph.study.research_goal,
        study_graph.persona_b.card_text,  # sibling persona
        study_graph.scenario.task,  # not part of the isolation boundary at M1
    ]
    for sentinel in forbidden:
        assert sentinel not in payload, f"leaked into PersonaContext: {sentinel!r}"

    # And confirm what *should* be present actually is, so this isn't a
    # vacuously-true test.
    assert study_graph.persona_a.card_text in payload
    assert "SENTINEL-ARTEFACT-BODY" in payload
    assert "SENTINEL-MODERATOR-OPENING" in payload


def test_persona_context_only_includes_moderator_turns(study_graph: StudyGraph) -> None:
    turns = [study_graph.turn_moderator, study_graph.turn_persona]
    context = PersonaContext.build(
        persona=study_graph.persona_a, artefact=study_graph.artefact, turns=turns
    )
    assert context.moderator_turns == [study_graph.turn_moderator.content]


def test_persona_panel_relationship_raises_on_lazy_load(
    session: Session, study_graph: StudyGraph
) -> None:
    """Backstop: if a persona-bound code path ever gets handed a live ORM
    `Persona` and tries to walk up to its Study, that must fail loudly.
    """
    session.expire_all()
    persona = session.get(type(study_graph.persona_a), study_graph.persona_a.id)
    assert persona is not None
    try:
        _ = persona.panel
    except InvalidRequestError:
        pass
    else:
        raise AssertionError(
            "Persona.panel should raise on lazy load, not silently succeed"
        )
