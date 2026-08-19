"""Shared fixtures: an in-memory SQLite session, a sentinel-laden object
graph, an offline network guard, and a scratch cassette directory.
"""

from __future__ import annotations

import socket
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from sul import models
from sul.db import create_all, make_engine, make_session_factory
from sul.enums import (
    AgentRole,
    ArtefactKind,
    FindingCategory,
    RunStatus,
    TurnRole,
)


class OfflineGuardError(RuntimeError):
    """Raised when a test attempts an outbound network connection.

    CLAUDE.md: "Tests must run fully offline. No test may hit a real LLM
    API, ever." This makes that provable in CI rather than a manual "run
    with network disabled" step (see the M2 implementation note in
    PROJECT_SPEC.md) — a blocked call fails loudly, it is never silently
    skipped.
    """


# asyncio's Windows `ProactorEventLoop` opens a loopback TCP "self-pipe"
# (`socket.socketpair`'s fallback on platforms without AF_UNIX) on *every*
# event loop it creates -- including the one pytest-asyncio spins up for
# each async test. That is local IPC, not "hitting a real LLM API"; blocking
# it outright would fail every async test before its body even runs. The
# guard therefore permits loopback addresses and blocks everything else.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_loopback(address: object) -> bool:
    return (
        isinstance(address, tuple)
        and bool(address)
        and isinstance(address[0], str)
        and address[0] in _LOOPBACK_HOSTS
    )


@pytest.fixture(scope="session", autouse=True)
def _block_network() -> Generator[None, None, None]:
    """Session-scoped, autouse: patch `socket` so any *non-loopback* outbound
    connection attempt during the whole test run raises `OfflineGuardError`
    naming the attempted address, instead of touching a real network.

    Deliberately not built on the `monkeypatch` fixture — that fixture is
    function-scoped only, and this guard must cover the whole session, so
    the original callables are saved and restored by hand instead.
    """
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection

    def _guarded_connect(
        self: socket.socket, address: object, *a: object, **kw: object
    ) -> None:
        if _is_loopback(address):
            original_connect(self, address, *a, **kw)  # type: ignore[arg-type]
            return
        raise OfflineGuardError(f"socket.connect() attempted: address={address!r}")

    def _guarded_connect_ex(
        self: socket.socket, address: object, *a: object, **kw: object
    ) -> int:
        if _is_loopback(address):
            result: int = original_connect_ex(self, address, *a, **kw)  # type: ignore[arg-type]
            return result
        raise OfflineGuardError(f"socket.connect_ex() attempted: address={address!r}")

    def _guarded_create_connection(
        address: object, *a: object, **kw: object
    ) -> socket.socket:
        if _is_loopback(address):
            result: socket.socket = original_create_connection(address, *a, **kw)  # type: ignore[arg-type]
            return result
        raise OfflineGuardError(
            f"socket.create_connection() attempted: address={address!r}"
        )

    socket.socket.connect = _guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[assignment]
    socket.create_connection = _guarded_create_connection
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create_connection


@pytest.fixture
def cassette_dir(tmp_path: Path) -> Path:
    """A scratch directory for cassette record/replay tests, isolated per test."""
    path = tmp_path / "cassettes"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None, None, None]:
    """`sul.config.get_settings` is process-cached (`lru_cache`); tests that
    monkeypatch the environment and clear it must not leak that clear (or
    the stale cached instance) into unrelated tests.
    """
    from sul.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """A `sessionmaker` against a fresh in-memory SQLite database, one per test.

    `StaticPool` keeps the same in-memory connection alive for the whole
    test (SQLite's `:memory:` database is otherwise per-connection and
    vanishes as soon as the connection pool hands back a different one).
    `session` (below) derives from this so both share one engine.
    """
    engine = make_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_all(engine)
    factory = make_session_factory(engine)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """A session from `session_factory`, one per test."""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


class StudyGraph:
    """The full object graph for one study, with every persona-visible-adjacent
    string replaced by a distinctive sentinel so `test_isolation.py` can prove
    none of them leak into a `PersonaContext`.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

        self.artefact = models.Artefact(
            name="bad_onboarding.html",
            kind=ArtefactKind.HTML,
            content_hash="sentinel-content-hash-0001",
            body="<html>SENTINEL-ARTEFACT-BODY</html>",
        )
        session.add(self.artefact)
        session.flush()

        self.study = models.Study(
            name="Onboarding friction study",
            research_goal="SENTINEL-RESEARCH-GOAL-do-not-leak-to-personas",
            artefact_id=self.artefact.id,
            config_hash="sentinel-config-hash",
            git_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        )
        session.add(self.study)
        session.flush()

        self.panel = models.Panel(
            study_id=self.study.id,
            seed=42,
            size=2,
            config_yaml="seed: 42\nsize: 2\n",
        )
        session.add(self.panel)
        session.flush()

        self.persona_a = models.Persona(
            panel_id=self.panel.id,
            name="Persona A",
            segment="time_poor_professional",
            attributes={"tech_comfort": "high", "patience": "low"},
            card_text="You are SENTINEL-PERSONA-A-CARD, a time-poor professional.",
        )
        self.persona_b = models.Persona(
            panel_id=self.panel.id,
            name="Persona B",
            segment="cost_sensitive_student",
            attributes={"tech_comfort": "medium", "patience": "medium"},
            card_text="You are SENTINEL-PERSONA-B-CARD, a cost-sensitive student.",
        )
        session.add_all([self.persona_a, self.persona_b])
        session.flush()

        self.scenario = models.Scenario(
            study_id=self.study.id,
            task="SENTINEL-SCENARIO-TASK: sign up for the trial.",
            questions=["Was anything unclear?"],
        )
        session.add(self.scenario)
        session.flush()

        self.run = models.Run(
            study_id=self.study.id,
            persona_id=self.persona_a.id,
            scenario_id=self.scenario.id,
            status=RunStatus.COMPLETED,
        )
        session.add(self.run)
        session.flush()

        self.model_call = models.ModelCall(
            run_id=self.run.id,
            agent=AgentRole.PERSONA,
            provider="fake",
            model="fake-1",
            prompt_hash="sentinel-prompt-hash",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            latency_ms=10,
            seed=42,
            cached=True,
        )
        session.add(self.model_call)
        session.flush()

        self.turn_moderator = models.Turn(
            run_id=self.run.id,
            role=TurnRole.MODERATOR,
            ordinal=0,
            content="SENTINEL-MODERATOR-OPENING: try signing up.",
        )
        self.turn_persona = models.Turn(
            run_id=self.run.id,
            role=TurnRole.PERSONA,
            ordinal=1,
            content="I got confused by the pricing.",
            model_call_id=self.model_call.id,
        )
        session.add_all([self.turn_moderator, self.turn_persona])
        session.flush()

        self.finding = models.Finding(
            run_id=self.run.id,
            category=FindingCategory.CONFUSION,
            severity=3,
            summary="Persona was confused by the pricing table.",
            evidence_turn_id=self.turn_persona.id,
        )
        session.add(self.finding)
        session.flush()


@pytest.fixture
def study_graph(session: Session) -> StudyGraph:
    """A persisted, full object graph: Study -> Artefact/Panel/Scenario -> Persona
    -> Run -> Turn/ModelCall -> Finding, with sentinel strings throughout.
    """
    return StudyGraph(session)


@pytest.fixture
def study_and_run(session_factory: sessionmaker[Session]) -> tuple[int, int]:
    """A minimal Study -> Artefact/Panel/Persona/Scenario -> Run graph, with
    no ModelCall or Turn rows -- for provider-layer tests (budget, structured
    output, recording) that need somewhere real to attribute a `ModelCall`
    to without pulling in the full sentinel-laden `StudyGraph`.
    """
    with session_factory() as session:
        artefact = models.Artefact(
            name="a.html", kind=ArtefactKind.HTML, content_hash="h1", body="<html/>"
        )
        session.add(artefact)
        session.flush()

        study = models.Study(
            name="provider-layer test study",
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
            study_id=study.id, persona_id=persona.id, scenario_id=scenario.id
        )
        session.add(run)
        session.commit()
        return study.id, run.id
