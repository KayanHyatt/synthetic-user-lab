"""The standing caveat on the dashboard (PROJECT_SPEC.md §M7 5.3):
`SIMULATED_PANEL_CAVEAT` (`sul.report.model`, unchanged, imported not
retyped) must appear on every route, including every HTMX partial, and no
HTMX swap this app declares can replace or hide the region carrying it.

The last claim is checked structurally, not by reading the templates: parse
every full page with `tests/support/dashboard_parse.py`, resolve every
`hx-target` (and self-targeting `hx-get`) to element ids, and assert the
caveat element's own id is neither one of those targets nor an ancestor-id
match for one -- i.e. the caveat is not *inside* anything an HTMX swap could
overwrite. `tests/test_web_routes.py`'s populated-database pattern is reused
via a local fixture.
"""

from __future__ import annotations

import pytest

from sul.config import get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.report.model import SIMULATED_PANEL_CAVEAT
from tests.support.dashboard_parse import htmx_swap_target_ids, parse_dashboard_page
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


def _all_routes(fixture: ReportFixture) -> list[str]:
    ana_run_id = fixture.run_ids["Ana"]
    return [
        "/",
        f"/studies/{fixture.study_id}/runs",
        f"/runs/{ana_run_id}",
        f"/partials/runs/{ana_run_id}/turns",
        f"/studies/{fixture.study_id}/report",
    ]


async def test_caveat_present_on_every_route(populated_db: ReportFixture) -> None:
    async with dashboard_client() as client:
        for route in _all_routes(populated_db):
            r = await client.get(route)
            assert r.status_code == 200, route
            assert SIMULATED_PANEL_CAVEAT in r.text, (
                f"{route} does not render the standing caveat"
            )


async def test_caveat_element_is_never_inside_an_htmx_swap_target(
    populated_db: ReportFixture,
) -> None:
    """Structural swap test, not just initial render: parse each *full page*
    (not the partial itself -- a partial has no `#standing-caveat` element
    of its own to test containment for, see the belt-and-braces test below),
    find every element an HTMX swap could write into, and assert the caveat
    element is neither one of them nor a descendant of one.
    """
    full_pages = [
        "/",
        f"/studies/{populated_db.study_id}/runs",
        f"/runs/{populated_db.run_ids['Ana']}",
        f"/studies/{populated_db.study_id}/report",
    ]
    async with dashboard_client() as client:
        for route in full_pages:
            r = await client.get(route)
            page = parse_dashboard_page(r.text)
            caveat_elements = [e for e in page.elements if e.id == "standing-caveat"]
            assert len(caveat_elements) == 1, (
                f"{route}: expected exactly one #standing-caveat element, "
                f"found {len(caveat_elements)}"
            )
            caveat_el = caveat_elements[0]
            target_ids = htmx_swap_target_ids(page)
            assert "standing-caveat" not in target_ids, (
                f"{route}: the caveat element itself is an HTMX swap target"
            )
            overlap = set(caveat_el.ancestor_ids) & target_ids
            assert not overlap, (
                f"{route}: the caveat is nested inside swap target(s) {overlap} "
                "-- a swap into any of them could hide it"
            )


async def test_no_route_uses_hx_swap_oob(populated_db: ReportFixture) -> None:
    """`hx-swap-oob` is the one HTMX feature that can write content outside
    its own declared target -- the ancestor-chain check above can't see that
    kind of swap coming, so it's forbidden outright rather than reasoned
    about.
    """
    async with dashboard_client() as client:
        for route in _all_routes(populated_db):
            r = await client.get(route)
            assert "hx-swap-oob" not in r.text, f"{route} uses hx-swap-oob"


async def test_partial_carries_the_caveat_text_belt_and_braces(
    populated_db: ReportFixture,
) -> None:
    """Even though the full page's caveat can never be swapped away (proved
    above), the partial repeats the caveat text in its own response body --
    so a response fetched standalone (curl, a future swap target, anything
    that only ever sees the partial's own innerHTML) still carries it.
    """
    ana_run_id = populated_db.run_ids["Ana"]
    async with dashboard_client() as client:
        r = await client.get(f"/partials/runs/{ana_run_id}/turns")
    assert r.status_code == 200
    assert SIMULATED_PANEL_CAVEAT in r.text
