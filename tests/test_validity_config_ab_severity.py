"""PROJECT_SPEC.md §M6 Deviation 20 follow-through: backs the severity claims
in `src/sul/validity/templates/limitations.md.j2`'s "do not transfer down a
model tier" paragraph with a committed, regenerable test, not scrollback --
`DiscriminativeValiditySection` carries category counts and a distinct-anchor
count (Deviation 20) but not a severity distribution, so the specific claim
that Config B "keeps the same two severity-4 findings Sonnet found but never
labels one of them a `blocker`... and shifts its middle mass down (mode
severity 3 -> 2)" was, until this test, asserted in prose only.

Calls `run_discriminative_validity` directly against the real, committed
`tests/cassettes/` (replay-only, `record=False`) for both Config A
(Haiku persona/moderator, Sonnet Analyst) and Config B (Haiku throughout) --
the same construction `tests/support/run_config_b_validity_report_script.py`
and `tests/test_docs_claims.py::pinned_report` use, one level lower (this
module's own `bad_rows`/`good_rows`, which carry `Finding.severity` --
`DiscriminativeValiditySection` does not).

Single-process, not cross-process: unlike the report-level determinism
tests in `tests/test_validity_cassette_report_determinism.py`, nothing here
touches `sul.analysis.clustering` (that module's own order-sensitivity is
about cluster *labels*, not `Finding.category`/`.severity` counts, which
`blocker_confusion_count`/`category_counts` already compute without
clustering) -- so there is no wall-clock/iteration-order defect class this
test needs to guard against.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import httpx
import pytest

from sul.db import create_all, make_engine, make_session_factory
from sul.enums import AgentRole
from sul.providers.anthropic import AnthropicProvider
from sul.providers.cassette import CassetteTransport
from sul.validity.discriminative import run_discriminative_validity

REPO_ROOT = Path(__file__).resolve().parents[1]
CASSETTE_DIR = REPO_ROOT / "tests" / "cassettes"

_MODEL = "claude-haiku-4-5"
_ANALYST_MODEL = "claude-sonnet-5"


async def _run(model_by_agent: dict[AgentRole, str] | None, db_dir: Path):
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "sul.db"
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)
    transport = CassetteTransport(
        httpx.AsyncHTTPTransport(), CASSETTE_DIR, record=False
    )
    provider = AnthropicProvider(
        "sul-severity-comparison-replay-only-sentinel-key", transport=transport
    )
    return await run_discriminative_validity(
        session_factory,
        provider=provider,
        provider_name="anthropic",
        model=_MODEL,
        model_by_agent=model_by_agent,
        base_path=REPO_ROOT,
    )


@pytest.mark.asyncio
async def test_config_b_bad_artefact_severity_shifts_categorically_not_by_severity(
    tmp_path: Path,
) -> None:
    config_a = await _run({AgentRole.ANALYST: _ANALYST_MODEL}, tmp_path / "a")
    config_b = await _run(None, tmp_path / "b")

    a_severity = Counter(r.severity for r in config_a.bad_rows)
    b_severity = Counter(r.severity for r in config_b.bad_rows)
    assert dict(a_severity) == {2: 1, 3: 5, 4: 2}
    assert dict(b_severity) == {1: 1, 2: 4, 4: 2}

    # Mode shifts down (3 -> 2); both keep exactly two severity-4 findings.
    assert a_severity.most_common(1)[0][0] == 3
    assert b_severity.most_common(1)[0][0] == 2
    assert a_severity[4] == b_severity[4] == 2

    # The two severity-4 findings themselves: Config A has one `blocker` and
    # one `missing_info`; Config B has zero `blocker` at severity 4 (or any
    # severity) -- the same severity ceiling, a different category.
    a_sev4_categories = {r.category.value for r in config_a.bad_rows if r.severity == 4}
    b_sev4_categories = {r.category.value for r in config_b.bad_rows if r.severity == 4}
    assert a_sev4_categories == {"blocker", "missing_info"}
    assert b_sev4_categories == {"confusion", "missing_info"}
    assert "blocker" not in {r.category.value for r in config_b.bad_rows}


@pytest.mark.asyncio
async def test_good_artefact_zero_is_all_delight_in_both_configs(
    tmp_path: Path,
) -> None:
    config_a = await _run({AgentRole.ANALYST: _ANALYST_MODEL}, tmp_path / "a")
    config_b = await _run(None, tmp_path / "b")

    assert {r.category.value for r in config_a.good_rows} == {"delight"}
    assert {r.category.value for r in config_b.good_rows} == {"delight"}

    a_personas = {r.persona_name for r in config_a.good_rows}
    b_personas = {r.persona_name for r in config_b.good_rows}
    assert len(a_personas) == 2
    assert len(b_personas) == 5
