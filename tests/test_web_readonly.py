"""Read-only enforcement for `sul.web` (PROJECT_SPEC.md §M7 5.5): the
dashboard's database connection is driver-enforced read-only (SQLite
`mode=ro` URI), not merely "we just don't write" by convention, and a
missing database file renders an explicit empty state rather than a 500.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from sul.config import get_settings
from sul.db import create_all, make_engine
from sul.models import Artefact
from sul.web.app import _read_only_session, _read_only_sqlite_url
from tests.support.web_client import dashboard_client


def test_read_only_sqlite_url_rejects_non_sqlite() -> None:
    with pytest.raises(ValueError, match="sqlite"):
        _read_only_sqlite_url("postgresql://user:pass@host/db")


def test_read_only_sqlite_url_rejects_in_memory() -> None:
    with pytest.raises(ValueError, match=":memory:"):
        _read_only_sqlite_url("sqlite:///:memory:")


def test_read_only_sqlite_url_produces_a_mode_ro_uri() -> None:
    ro_url, db_path = _read_only_sqlite_url("sqlite:///some/path/sul.db")
    assert ro_url.startswith("sqlite:///file:")
    assert "mode=ro" in ro_url
    assert "uri=true" in ro_url
    assert str(db_path) in ("some/path/sul.db", "some\\path\\sul.db")


def test_read_only_session_is_none_when_database_file_is_missing(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.db"
    with _read_only_session(f"sqlite:///{missing}") as session:
        assert session is None


def test_read_only_session_cannot_write(file_db_path) -> None:
    """The connection itself refuses a write -- not "nothing in this
    codebase happens to call session.add()", an actual driver-level
    rejection of an INSERT attempted directly against the read-only session.
    """
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    engine.dispose()

    with _read_only_session(f"sqlite:///{file_db_path}") as session:
        assert session is not None
        session.add(Artefact(name="x", kind="html", content_hash="h", body="<html/>"))
        with pytest.raises(sa.exc.OperationalError, match="readonly|read-only"):
            session.flush()


def test_read_only_session_disposes_its_engine_and_releases_the_file(
    file_db_path,
) -> None:
    """A read-only session that leaked its engine would eventually hard-lock
    the SQLite file on Windows (found while building this dashboard --
    see `sul.web.app._read_only_session`'s own docstring). Proven here by
    opening many short-lived read-only sessions and then successfully
    deleting the file afterward -- a held file handle would make the
    deletion fail on Windows.
    """
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    engine.dispose()

    for _ in range(20):
        with _read_only_session(f"sqlite:///{file_db_path}") as session:
            assert session is not None
            session.execute(sa.select(Artefact)).all()

    file_db_path.unlink()  # raises on Windows if any handle is still open
    assert not file_db_path.exists()


async def test_index_renders_empty_state_without_a_database_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does_not_exist.db"
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{missing}")
    get_settings.cache_clear()

    async with dashboard_client() as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert "No studies yet" in r.text


async def test_runs_page_is_404_without_a_database_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does_not_exist.db"
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{missing}")
    get_settings.cache_clear()

    async with dashboard_client() as client:
        r = await client.get("/studies/1/runs")
    assert r.status_code == 404
    assert "sul demo" in r.text.lower()
