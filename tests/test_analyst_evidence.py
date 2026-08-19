"""§M4 carry-forward: every Analyst finding's evidence must be verified
against the stored transcript before it can land in a `Finding`, rejected
loudly on mismatch.

This codebase's mechanism (a documented deviation from a literal reading of
the carry-forward -- see PROJECT_SPEC.md's M4 implementation note) is a
reference, not a re-typed quote: `evidence_turn_ordinal` is typed `Literal`
over exactly this run's own persona-turn ordinals
(`sul.schemas.agents.build_analyst_response_schema`), so an out-of-range
reference is a schema-validation failure -- handled by the same one-repair-
turn path as any other malformed structured output, not a second, separate
verification step.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.enums import RunStatus
from sul.providers.base import Completion, Message
from sul.providers.fake import FakeProvider
from sul.runner.orchestrator import run_study
from sul.schemas.agents import PersonaReply
from tests.support.scripted_provider import ScriptedProvider, text_completion
from tests.support.study_factory import build_materialized_study


@pytest.mark.asyncio
async def test_finding_evidence_resolves_to_a_real_persona_turn_in_the_same_run(
    session_factory: sessionmaker[Session],
) -> None:
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_2.yaml"
    )
    await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        max_followups=0,
    )
    with session_factory() as session:
        findings = session.execute(select(models.Finding)).scalars().all()
        assert findings, "expected FakeProvider to synthesize at least one finding"
        for finding in findings:
            run = session.get(models.Run, finding.run_id)
            assert run is not None
            evidence_turn = session.get(models.Turn, finding.evidence_turn_id)
            assert evidence_turn is not None
            assert evidence_turn.run_id == finding.run_id
            assert evidence_turn.role.value == "persona"


@pytest.mark.asyncio
async def test_out_of_range_evidence_ordinal_is_rejected_loudly(
    session_factory: sessionmaker[Session],
) -> None:
    """An Analyst response citing a turn ordinal outside this run's own
    transcript fails schema validation (same path as any malformed
    structured output): one repair turn, still malformed, terminal
    `StructuredOutputError`, no `Finding` row ever written for it.
    """
    materialized = build_materialized_study(
        session_factory, panel_path="tests/fixtures/panel_1.yaml"
    )

    def script(
        index: int,
        messages: list[Message],
        model: str,
        seed: int | None,
        response_schema: type[BaseModel] | None,
    ) -> Completion:
        if response_schema is PersonaReply:
            return text_completion(
                PersonaReply(utterance="hi", state="completed").model_dump_json()
            )
        if response_schema is not None and "findings" in response_schema.model_fields:
            return text_completion(
                '{"findings": [{"category": "blocker", "severity": 3, '
                '"summary": "s", "evidence_turn_ordinal": 999}]}'
            )
        return text_completion("ok")

    provider = ScriptedProvider(script=script)
    summary = await run_study(
        session_factory,
        study_id=materialized.study_id,
        scenario_id=materialized.scenario_id,
        provider=provider,
        provider_name="fake",
        model="fake-1",
        max_followups=0,
    )
    assert len(summary.completed) == 0
    assert len(summary.failed) == 1

    with session_factory() as session:
        run = session.execute(select(models.Run)).scalar_one()
        assert run.status == RunStatus.FAILED
        assert run.error is not None
        findings = (
            session.execute(
                select(models.Finding).where(models.Finding.run_id == run.id)
            )
            .scalars()
            .all()
        )
        assert findings == []
