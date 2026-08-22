"""`sul.web`'s routes (PROJECT_SPEC.md §M7): study list -> run list ->
transcript view -> report view, all read-only. Populated via
`tests/support/report_factory.py`'s hand-built fixture (the same one M5's
own report tests use, `build_report_fixture`), against a real, on-disk
SQLite database (`file_db_path`, `tests/conftest.py`) -- the dashboard opens
its own separate engine, so an in-memory `:memory:` database (the ordinary
`session`/`session_factory` fixtures) can't be shared with it.
"""

from __future__ import annotations

import pytest

from sul.config import get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.report.build import build_report
from tests.support.html_parse import parse_report_html
from tests.support.report_factory import ReportFixture, build_report_fixture
from tests.support.web_client import dashboard_client


@pytest.fixture
def populated_db(file_db_path, monkeypatch: pytest.MonkeyPatch) -> ReportFixture:
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        fixture = build_report_fixture(session)
    engine.dispose()
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{file_db_path}")
    get_settings.cache_clear()
    return fixture


async def test_index_lists_the_study(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert "M5 report fixture study" in r.text


async def test_index_is_empty_state_when_no_studies_recorded(
    file_db_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No fixture built at all -- distinct from `test_readonly`'s
    "database file doesn't exist" case: here the file exists (`create_all`
    ran) but holds zero studies.
    """
    engine = make_engine(f"sqlite:///{file_db_path}")
    create_all(engine)
    engine.dispose()
    monkeypatch.setenv("SUL_DATABASE_URL", f"sqlite:///{file_db_path}")
    get_settings.cache_clear()

    async with dashboard_client() as client:
        r = await client.get("/")
    assert r.status_code == 200
    assert "No studies yet" in r.text


async def test_runs_page_lists_every_persona(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        r = await client.get(f"/studies/{populated_db.study_id}/runs")
    assert r.status_code == 200
    for name in ("Ana", "Ben", "Cid", "Dee", "Eve"):
        assert name in r.text
    # Statuses from the fixture: Ana/Ben/Cid completed, Dee failed, Eve pending.
    assert "completed" in r.text
    assert "failed" in r.text
    assert "pending" in r.text


async def test_unknown_study_runs_is_404(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        r = await client.get("/studies/999999/runs")
    assert r.status_code == 404


async def test_transcript_page_renders_real_turns(populated_db: ReportFixture) -> None:
    ana_run_id = populated_db.run_ids["Ana"]
    async with dashboard_client() as client:
        r = await client.get(f"/runs/{ana_run_id}")
    assert r.status_code == 200
    assert "I could not find the submit button anywhere." in r.text
    assert "Ana" in r.text


async def test_unknown_run_is_404(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        r = await client.get("/runs/999999")
    assert r.status_code == 404


async def test_partial_serves_the_same_transcript_as_the_full_page(
    populated_db: ReportFixture,
) -> None:
    ana_run_id = populated_db.run_ids["Ana"]
    async with dashboard_client() as client:
        full = await client.get(f"/runs/{ana_run_id}")
        partial = await client.get(f"/partials/runs/{ana_run_id}/turns")
    assert partial.status_code == 200
    assert "I could not find the submit button anywhere." in partial.text
    # The partial is a fragment, not a full page -- no <html>/<nav> wrapper.
    assert "<html" not in partial.text
    assert "<html" in full.text


async def test_unknown_run_partial_is_404(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        r = await client.get("/partials/runs/999999/turns")
    assert r.status_code == 404


async def test_report_page_renders_the_same_report_build_report_returns(
    populated_db: ReportFixture, file_db_path
) -> None:
    """The dashboard's report view must render `build_report`'s own
    `ReportModel` -- never re-query or re-rank (PROJECT_SPEC.md §M7 4).
    Compares the dashboard page, parsed structurally
    (`tests/support/html_parse.py`, the same parser M5's report tests use --
    it works unchanged here because the dashboard shares `_clusters.html.j2`
    with `sul.report.html`), against a `build_report` call over the same
    database.
    """
    engine = make_engine(f"sqlite:///{file_db_path}")
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        expected = build_report(session, study_id=populated_db.study_id)
    engine.dispose()

    async with dashboard_client() as client:
        r = await client.get(f"/studies/{populated_db.study_id}/report")
    assert r.status_code == 200

    clusters, external_refs = parse_report_html(r.text)
    # `parse_report_html`'s `external_refs` (built for M5's report, which has
    # zero <script> tags at all) flags *any* script src, local or not -- the
    # dashboard's one local, vendored `<script src="/static/htmx.min.js">`
    # is exactly what it's meant to catch happening *without* being local.
    # tests/test_web_escaping.py's `test_no_external_network_references`
    # uses the http(s)-gated check instead, over every route.
    assert external_refs == ["/static/htmx.min.js"]
    assert len(clusters) == len(expected.clusters) == 1
    assert len(clusters[0].quotes) == expected.total_findings == 3
    assert sorted(clusters[0].finding_ids) == sorted(
        e.finding_id for e in expected.clusters[0].evidence
    )


async def test_unknown_study_report_is_404(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        r = await client.get("/studies/999999/report")
    assert r.status_code == 404
