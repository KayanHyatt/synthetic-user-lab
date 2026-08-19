"""PROJECT_SPEC.md §M6.2. `is_material_difference` is tested against
hand-built counts (the negative control: it must say "no" for two identical
counts and "yes" for a deliberately large, real gap) independently of any
provider. The FakeProvider integration test only proves the two-artefact
pipeline runs end to end offline without error -- per the M6 design
conversation, it must NOT assert a direction for `material_difference`,
since FakeProvider's category draws are content-blind and any observed gap
would be sampling noise, not evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import ArtefactKind, FindingCategory, RunStatus, TurnRole
from sul.providers.fake import FakeProvider
from sul.validity.data import load_finding_rows
from sul.validity.discriminative import (
    blocker_confusion_count,
    is_material_difference,
    run_discriminative_validity,
)
from tests.support.report_factory import build_report_fixture

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_is_material_difference_says_no_for_identical_counts() -> None:
    assert is_material_difference(3, 3) is False
    assert is_material_difference(0, 0) is False


def test_is_material_difference_detects_a_real_gap() -> None:
    """Negative control: a fixture where the bad artefact's count is
    obviously, deliberately worse must be flagged -- if this ever returned
    False here, the rule would be structurally incapable of ever passing,
    which is exactly the "can only fail" mirror image of the "can only pass"
    failure mode this milestone exists to prevent.
    """
    assert is_material_difference(6, 1) is True


def test_is_material_difference_rejects_a_small_absolute_gap() -> None:
    """A 1-vs-0 count is a 'material' ratio but not a material absolute
    difference at this panel's size -- the rule must not fire on it.
    """
    assert is_material_difference(1, 0) is False


def _build_minimal_good_study(session: Session) -> int:
    """A second, minimal study with exactly one BLOCKER finding -- not
    `report_factory.build_single_finding_fixture`, which hardcodes the same
    `content_hash="h1"` `build_report_fixture` already used in this test:
    the two collide on `Artefact.content_hash`'s uniqueness constraint if
    called in the same session (the same class of bug the real `sul
    validate` invocation hit -- see `tests/test_cli_validate.py`). This
    inlines the same shape with a distinct hash rather than adding a second
    general-purpose fixture builder for one call site.
    """
    artefact = models.Artefact(
        name="good.html", kind=ArtefactKind.HTML, content_hash="h2", body="<html/>"
    )
    session.add(artefact)
    session.flush()
    study = models.Study(
        name="good study",
        research_goal="goal",
        artefact_id=artefact.id,
        config_hash="c2",
        git_sha="f" * 40,
    )
    session.add(study)
    session.flush()
    scenario = models.Scenario(study_id=study.id, task="task", questions=[])
    panel = models.Panel(study_id=study.id, seed=1, size=1, config_yaml="")
    session.add_all([scenario, panel])
    session.flush()
    persona = models.Persona(
        panel_id=panel.id, name="Solo", segment="seg", attributes={}, card_text="c"
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
    turn = models.Turn(
        run_id=run.id, role=TurnRole.PERSONA, ordinal=0, content="It was fine."
    )
    session.add(turn)
    session.flush()
    finding = models.Finding(
        run_id=run.id,
        category=FindingCategory.BLOCKER,
        severity=2,
        summary="No problems reported.",
        evidence_turn_id=turn.id,
    )
    session.add(finding)
    session.commit()
    return study.id


def test_material_difference_is_wired_through_real_db_loaded_rows(
    session: Session,
) -> None:
    """Not a synthetic in-memory list: `bad_rows`/`good_rows` here are loaded
    by `load_finding_rows`, the same SQL path `run_discriminative_validity`
    itself uses, from two studies persisted through the database. This is
    the "real harness path" version of the pure-function test above -- it
    proves the SQL query, `FindingRow` construction, and the comparison
    function are wired together correctly, not just that the comparison
    function is correct in isolation.

    `build_report_fixture` (M5's own fixture builder, reused rather than
    forked) gives Ana (2 BLOCKER findings) + Ben (1 BLOCKER finding) = 3; the
    minimal good study above gives exactly 1. 3 vs 1 is a deliberate, known
    material gap (>= 1.5x and >= 2 absolute).
    """
    bad_fixture = build_report_fixture(session)
    good_study_id = _build_minimal_good_study(session)

    bad_rows = load_finding_rows(session, study_id=bad_fixture.study_id)
    good_rows = load_finding_rows(session, study_id=good_study_id)

    bad_count = blocker_confusion_count(bad_rows)
    good_count = blocker_confusion_count(good_rows)
    assert bad_count == 3
    assert good_count == 1
    assert is_material_difference(bad_count, good_count) is True


@pytest.mark.asyncio
async def test_fakeprovider_runs_both_artefacts_end_to_end_offline(
    session_factory: sessionmaker[Session],
) -> None:
    result = await run_discriminative_validity(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        panel_path="tests/fixtures/panel_2.yaml",
        base_path=REPO_ROOT,
    )
    assert result.bad_blocker_confusion_count >= 0
    assert result.good_blocker_confusion_count >= 0
