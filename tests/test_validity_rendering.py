"""PROJECT_SPEC.md §M6: the `NOT_MEASURED_OFFLINE` sentinel must be visibly
distinct in rendered output, never a bare `None`/`0`/empty string standing in
for a real measurement (per the M6 design conversation). `docs/limitations.md`
must name at least two concrete, measured weaknesses (the acceptance
criterion), and must not count the four provider-gated checks toward that.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sul.providers.fake import FakeProvider
from sul.validity.harness import run_validity_harness
from sul.validity.limitations import render_limitations_markdown
from sul.validity.markdown import render_validity_markdown

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_not_measured_offline_renders_distinctly_never_as_none_or_zero(
    session_factory: sessionmaker[Session],
) -> None:
    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )
    text = render_validity_markdown(report)

    assert text.count("NOT MEASURED OFFLINE") == 4
    # None of the four gated sections' numeric fields print as bare "None".
    assert "material_difference: None" not in text
    assert "Material difference: None" not in text
    # The reproducibility section (always measured) is not gated.
    assert "Finding count variance: NOT MEASURED OFFLINE" not in text
    assert str(report.reproducibility.finding_count_variance) in text


@pytest.mark.asyncio
async def test_limitations_md_states_at_least_two_measured_weaknesses(
    session_factory: sessionmaker[Session],
) -> None:
    report = await run_validity_harness(
        session_factory,
        provider=FakeProvider(),
        provider_name="fake",
        model="fake-1",
        base_path=REPO_ROOT,
    )
    text = render_limitations_markdown(report)

    measured_weakness_headers = [
        "Cluster themes partly reflect the Analyst's writing style",
        "A rare theme and a broken measurement look identical",
        "Cluster granularity at a fixed threshold is unmeasured territory",
    ]
    present = [h for h in measured_weakness_headers if h in text]
    assert len(present) >= 2

    # The four provider-gated checks are named, but explicitly not counted.
    assert "not counted toward the two measured weaknesses" in text
