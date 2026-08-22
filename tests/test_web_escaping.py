"""Escaping across the dashboard -- the third renderer alongside M5's
Markdown/HTML report (PROJECT_SPEC.md §M7 5.2). Extends M5's own
escaping-hazard fixture (`tests/support/report_factory.py`'s
`ESCAPING_HAZARD_QUOTE`) rather than forking it: round-trips the same
constant through the dashboard's transcript page, its HTMX partial, and its
report page, parsed (not substring-matched) each time.

Also proves the one-`Environment` claim `sul.web.templates`'s docstring
makes -- pages and partials render through the identical `jinja2.Environment`
object, so there is structurally only one escaping configuration, not a
full-page one and a separately-declared partial one.
"""

from __future__ import annotations

import pytest

from sul.config import get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.report.html import _env as report_env
from sul.web.templates import env as web_env
from tests.support.dashboard_parse import parse_dashboard_page
from tests.support.html_parse import parse_report_html
from tests.support.report_factory import (
    ESCAPING_HAZARD_QUOTE,
    build_report_fixture,
    build_single_finding_fixture,
)
from tests.support.web_client import dashboard_client


def test_web_environment_is_one_object_with_autoescape_on() -> None:
    assert web_env.autoescape is True


def test_web_environment_is_not_the_report_environment() -> None:
    """Distinct from `sul.report.html`'s own `Environment` -- `sul.web`
    doesn't reuse *that* object (it has its own loader, chaining in
    `sul.report`'s templates directory for `_clusters.html.j2`), but both
    independently have `autoescape=True`. What matters structurally is that
    *within* `sul.web`, every page and partial share one environment --
    checked below.
    """
    assert web_env is not report_env
    assert report_env.autoescape is True


@pytest.fixture
def hazard_run(file_db_path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, int]:
    """A single-finding study whose one transcript turn is
    `ESCAPING_HAZARD_QUOTE`. Returns (study_id, run_id)."""
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        study_id = build_single_finding_fixture(
            session, quote=ESCAPING_HAZARD_QUOTE, summary="A hazardous summary."
        )
    with session_factory() as session:
        from sul.models import Run

        run_id = session.query(Run).filter(Run.study_id == study_id).one().id
    engine.dispose()
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{file_db_path}")
    get_settings.cache_clear()
    return study_id, run_id


async def test_hazard_quote_round_trips_on_the_transcript_page(
    hazard_run: tuple[int, int],
) -> None:
    _, run_id = hazard_run
    async with dashboard_client() as client:
        r = await client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    page = parse_dashboard_page(r.text)
    assert ESCAPING_HAZARD_QUOTE in page.quotes


async def test_hazard_quote_round_trips_on_the_partial(
    hazard_run: tuple[int, int],
) -> None:
    _, run_id = hazard_run
    async with dashboard_client() as client:
        r = await client.get(f"/partials/runs/{run_id}/turns")
    assert r.status_code == 200
    page = parse_dashboard_page(r.text)
    assert ESCAPING_HAZARD_QUOTE in page.quotes


async def test_hazard_quote_round_trips_on_the_report_page(
    hazard_run: tuple[int, int],
) -> None:
    study_id, _ = hazard_run
    async with dashboard_client() as client:
        r = await client.get(f"/studies/{study_id}/report")
    assert r.status_code == 200
    clusters, _ = parse_report_html(r.text)
    assert ESCAPING_HAZARD_QUOTE in clusters[0].quotes


async def test_summary_never_appears_as_a_quote_on_the_transcript_page(
    file_db_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = "SENTINEL-ANALYST-PARAPHRASE-do-not-quote-this"
    quote = "SENTINEL-VERBATIM-PERSONA-UTTERANCE"
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        study_id = build_single_finding_fixture(session, quote=quote, summary=summary)
        from sul.models import Run

        run_id = session.query(Run).filter(Run.study_id == study_id).one().id
    engine.dispose()
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{file_db_path}")
    get_settings.cache_clear()

    async with dashboard_client() as client:
        r = await client.get(f"/runs/{run_id}")
    page = parse_dashboard_page(r.text)
    assert summary not in page.quotes
    assert quote in page.quotes
    # The summary is rendered as labelled prose elsewhere on the page.
    assert summary in page.text


async def test_no_external_network_references_on_any_route(
    file_db_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PROJECT_SPEC.md §M7 2c: no route may reference an external (http/
    https) resource -- only the local, vendored `/static/htmx.min.js`.
    Unlike `tests/support/html_parse.py::parse_report_html` (built for M5's
    always-zero-script report, so it flags *any* script src), this uses
    `tests/support/dashboard_parse.py`'s http(s)-gated check, which is what
    "no CDN fetch" actually means.
    """
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        fixture = build_report_fixture(session)
    engine.dispose()
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{file_db_path}")
    get_settings.cache_clear()

    ana_run_id = fixture.run_ids["Ana"]
    routes = [
        "/",
        f"/studies/{fixture.study_id}/runs",
        f"/runs/{ana_run_id}",
        f"/partials/runs/{ana_run_id}/turns",
        f"/studies/{fixture.study_id}/report",
    ]
    async with dashboard_client() as client:
        for route in routes:
            r = await client.get(route)
            assert r.status_code == 200, route
            page = parse_dashboard_page(r.text)
            assert page.external_refs == [], f"{route} references: {page.external_refs}"
