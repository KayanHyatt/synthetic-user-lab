"""The FastAPI app: study list -> run list -> transcript view -> report view,
all read-only (PROJECT_SPEC.md §M7: "FastAPI + Jinja/HTMX dashboard...
Read-only is fine" -- this module takes the stronger reading deliberately,
see `sul.web`'s package docstring).

Every route opens its own driver-enforced read-only SQLite connection
(`_read_only_session`, SQLite's `mode=ro` URI) rather than relying on
convention -- a route that tried to write would get a `sqlite3.OperationalError`
from the driver itself, not just from nobody having written a `session.add(...)`
call yet. The database path comes from `Settings.database_url`
(`SUL_DATABASE_URL`, same setting `sul cost`/`sul report`/`sul validate`
already read) -- there is no hardcoded path here, and no assumption that the
file exists yet: a missing database renders an explicit empty state rather
than a 500 (a fresh clone that hasn't run `sul demo` yet is the expected
first encounter, not an error case).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from sul.config import get_settings
from sul.db import make_engine, make_session_factory
from sul.report.build import StudyNotFoundError, build_report
from sul.web import queries
from sul.web.templates import render_template

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _read_only_sqlite_url(database_url: str) -> tuple[str, Path]:
    """Turn a plain `sqlite:///<path>` URL into a `mode=ro`, `uri=true`
    variant SQLite's own driver enforces as read-only, plus the plain
    filesystem path (for the existence check `mode=ro` itself can't make,
    since opening a *missing* file in `mode=ro` raises rather than creating
    one).

    Only `sqlite:///<path>` is supported -- the only shape this project ever
    configures (`sul.db.make_engine`'s foreign-key PRAGMA listener already
    assumes SQLite elsewhere) -- and only a file-backed path, never
    `:memory:`, since a read-only dashboard process and the process that
    populated the database are always separate processes here.
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(
            f"the dashboard requires a 'sqlite:///<path>' database_url, "
            f"got {database_url!r}"
        )
    raw_path = database_url[len(prefix) :]
    if raw_path in ("", ":memory:") or raw_path.startswith("file::memory:"):
        raise ValueError(
            "the dashboard requires a file-backed sqlite database, not :memory:"
        )
    db_path = Path(raw_path)
    ro_url = f"{prefix}file:{db_path.as_posix()}?mode=ro&uri=true"
    return ro_url, db_path


@contextmanager
def _read_only_session(database_url: str) -> Generator[Session | None, None, None]:
    """A read-only `Session` over `database_url`, or `None` if the database
    file doesn't exist yet -- one engine per request, disposed on exit.

    The dashboard is a long-running server process, unlike `sul cost`/`sul
    report`/`sul validate` (one-shot CLI invocations that exit right after
    their single engine goes out of scope, so those never call `.dispose()`
    either). Reusing that same one-engine-per-call shape here without
    disposal would leak a SQLite file handle on every request -- harmless on
    Linux, but confirmed here to hard-lock the database file on Windows
    (a write from another process, e.g. a concurrent `sul run`, would fail)
    after only a handful of requests. Disposing per request costs one local
    file open/close, negligible for SQLite.
    """
    ro_url, db_path = _read_only_sqlite_url(database_url)
    if not db_path.exists():
        yield None
        return
    engine = make_engine(ro_url)
    try:
        session_factory = make_session_factory(engine)
        with session_factory() as session:
            yield session
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    """Build the dashboard app. `Settings.database_url` is re-read from
    `get_settings()` inside each request handler, not captured once here --
    the same pattern `sul.cli`'s commands use, and what lets tests point the
    app at a scratch database via `SUL_DATABASE_URL` + `get_settings
    .cache_clear()` (`tests/conftest.py`'s `_reset_settings_cache` autouse
    fixture already resets that cache between tests).
    """
    app = FastAPI(title="Synthetic User Lab")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def studies_index() -> str:
        with _read_only_session(get_settings().database_url) as session:
            if session is None:
                return render_template("studies.html.j2", studies=[])
            items = queries.list_studies(session)
        return render_template("studies.html.j2", studies=items)

    @app.get("/studies/{study_id}/runs", response_class=HTMLResponse)
    def study_runs(study_id: int) -> str:
        with _read_only_session(get_settings().database_url) as session:
            if session is None:
                raise HTTPException(404, "no database yet -- run `sul demo` first")
            study_name = queries.get_study_name(session, study_id)
            if study_name is None:
                raise HTTPException(404, f"no study with id={study_id}")
            runs = queries.list_runs(session, study_id)
        return render_template(
            "runs.html.j2", study_id=study_id, study_name=study_name, runs=runs
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_transcript(run_id: int) -> str:
        with _read_only_session(get_settings().database_url) as session:
            if session is None:
                raise HTTPException(404, "no database yet -- run `sul demo` first")
            transcript = queries.load_transcript(session, run_id)
        if transcript is None:
            raise HTTPException(404, f"no run with id={run_id}")
        return render_template("transcript.html.j2", transcript=transcript)

    @app.get("/partials/runs/{run_id}/turns", response_class=HTMLResponse)
    def run_turns_partial(run_id: int) -> str:
        with _read_only_session(get_settings().database_url) as session:
            if session is None:
                raise HTTPException(404, "no database yet -- run `sul demo` first")
            transcript = queries.load_transcript(session, run_id)
        if transcript is None:
            raise HTTPException(404, f"no run with id={run_id}")
        return render_template("partials/turns.html.j2", transcript=transcript)

    @app.get("/studies/{study_id}/report", response_class=HTMLResponse)
    def study_report(study_id: int) -> str:
        with _read_only_session(get_settings().database_url) as session:
            if session is None:
                raise HTTPException(404, "no database yet -- run `sul demo` first")
            try:
                report = build_report(session, study_id=study_id)
            except StudyNotFoundError:
                raise HTTPException(404, f"no study with id={study_id}") from None
        return render_template("dashboard_report.html.j2", report=report)

    return app


__all__ = ["create_app"]
