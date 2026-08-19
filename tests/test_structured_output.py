"""Malformed model output fails loudly (PROJECT_SPEC.md §M2).

Parsing into the Pydantic model is the only accepted path: unparseable
JSON, missing fields, or wrong shape all raise `StructuredOutputError`
carrying the raw text -- never a default, an empty model, a regex fallback,
or a silent retry-until-parse. The spec requires exactly one bounded repair
turn ("your output failed validation, here is the error") before giving up,
so a provider that is malformed on every attempt writes exactly two
`ModelCall` rows: the original dispatch and the repair dispatch -- both
billed, only the second one's failure is terminal.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from sul.enums import AgentRole
from sul.models import ModelCall
from sul.providers.base import Completion, Message, Usage
from sul.providers.client import ModelClient, StructuredOutputError


class Verdict(BaseModel):
    approved: bool
    reason: str


class AlwaysMalformedProvider:
    """Returns the same broken text on every call -- both the original
    attempt and the repair turn fail to parse.
    """

    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text
        self.dispatch_count = 0

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion:
        self.dispatch_count += 1
        return Completion(
            text=self.raw_text,
            usage=Usage(tokens_in=10, tokens_out=5),
            model=model,
            stop_reason="end_turn",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_text",
    [
        pytest.param("not json at all {{{", id="unparseable-json"),
        pytest.param('{"approved": true}', id="missing-field"),
        # A dict can't coerce to bool under any of Pydantic's lenient string
        # rules (unlike e.g. "yes"/"1", which Pydantic *does* accept as
        # truthy) -- this is genuinely, unambiguously the wrong shape.
        pytest.param('{"approved": {"nested": true}, "reason": "ok"}', id="wrong-type"),
        pytest.param("{}", id="empty-object"),
        pytest.param("[]", id="json-array-not-object"),
    ],
)
async def test_malformed_output_raises_after_one_repair_attempt(
    session_factory: sessionmaker[Session],
    study_and_run: tuple[int, int],
    raw_text: str,
) -> None:
    _study_id, run_id = study_and_run
    provider = AlwaysMalformedProvider(raw_text)
    client = ModelClient(
        provider, "fake", session_factory, agent=AgentRole.PERSONA, run_id=run_id
    )

    with pytest.raises(StructuredOutputError) as exc_info:
        await client.complete(
            messages=[Message(role="user", content="Assess this form.")],
            model="fake-1",
            temperature=0.0,
            max_tokens=100,
            seed=1,
            response_schema=Verdict,
        )

    error = exc_info.value
    assert error.raw_text == raw_text
    assert error.schema is Verdict
    assert error.attempts == 2
    assert provider.dispatch_count == 2  # original attempt + exactly one repair turn

    with session_factory() as session:
        rows = session.query(ModelCall).filter(ModelCall.run_id == run_id).all()
        assert len(rows) == 2


class RepairsSuccessfullyProvider:
    """Fails to parse on the first call, returns valid output on the repair
    turn -- proves the repair path is actually exercised, not merely present.
    """

    def __init__(self) -> None:
        self.dispatch_count = 0

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion:
        self.dispatch_count += 1
        text = (
            "{not valid json"
            if self.dispatch_count == 1
            else '{"approved": true, "reason": "looks fine"}'
        )
        return Completion(
            text=text,
            usage=Usage(tokens_in=10, tokens_out=5),
            model=model,
            stop_reason="end_turn",
        )


@pytest.mark.asyncio
async def test_repair_turn_can_succeed(
    session_factory: sessionmaker[Session], study_and_run: tuple[int, int]
) -> None:
    _study_id, run_id = study_and_run
    provider = RepairsSuccessfullyProvider()
    client = ModelClient(
        provider, "fake", session_factory, agent=AgentRole.PERSONA, run_id=run_id
    )

    result = await client.complete(
        messages=[Message(role="user", content="Assess this form.")],
        model="fake-1",
        temperature=0.0,
        max_tokens=100,
        seed=1,
        response_schema=Verdict,
    )

    assert isinstance(result, Verdict)
    assert result.approved is True
    assert provider.dispatch_count == 2

    with session_factory() as session:
        rows = session.query(ModelCall).filter(ModelCall.run_id == run_id).all()
        assert len(rows) == 2
