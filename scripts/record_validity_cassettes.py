"""Record real Anthropic traffic for the M6 validity harness's two-model
configuration pass (PROJECT_SPEC.md §M6, "two-configuration recording pass").

Deliberately outside pytest (CLAUDE.md: "Tests must run fully offline. No
test may hit a real LLM API, ever.") and outside `sul validate` (that command
never constructs anything but `FakeProvider` -- see
`sul.validity.harness`'s module docstring, and
`tests/test_validity_cassette_plumbing.py`'s docstring, which calls a
cassette-backed real run "a separate, explicitly invoked path"). This script
is that path, run once by hand -- it spends real money and requires
`ANTHROPIC_API_KEY` in the environment.

Config A: Persona/Moderator/probes on Haiku, Analyst on Sonnet.
Config B: everything on Haiku -- the Analyst re-run at a different model
against the *same* transcripts.

Both configs write into one shared cassette directory
(`tests/cassettes/`, `Settings.cassette_dir`'s default) with
`record_if_missing=True` (`sul.providers.cassette.CassetteTransport`): a
request whose key (method + scrubbed URL + canonicalised body) already has a
cassette on disk is replayed, not re-dispatched. Because Config B's
Persona/Moderator/probe requests are byte-identical to Config A's (same
Haiku model, same prompts, same deterministic seeds), only Config B's
Analyst-on-Haiku requests are actually new -- everything else replays for
free. This is what "B is A with the Analyst swapped" means in practice.

Usage:
    uv run python scripts/record_validity_cassettes.py [--db-path PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

import httpx
from sqlalchemy import func, select

from sul.config import get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.enums import AgentRole
from sul.models import ModelCall
from sul.providers.anthropic import AnthropicProvider
from sul.providers.cassette import CassetteTransport
from sul.validity.harness import run_validity_harness

REPO_ROOT = Path(__file__).resolve().parents[1]
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"


def _make_provider(api_key: str, cassette_dir: Path) -> AnthropicProvider:
    transport = CassetteTransport(
        httpx.AsyncHTTPTransport(),
        cassette_dir,
        record=True,
        record_if_missing=True,
    )
    return AnthropicProvider(api_key, transport=transport)


def _report_notional_cost(session_factory: object, label: str) -> None:
    """`ModelCall.cost_usd` is computed from the response's reported usage
    regardless of whether that response came from the network or a cassette
    replay (`ModelClient` never sees which) -- so this is "what these calls
    would cost if dispatched fresh", the same number `sul cost` would show,
    not the incremental real-dollar spend of *this* phase. See
    `_new_cassette_count` for the real, ground-truth figure: real money was
    only spent for a key that got a *new* cassette file.
    """
    with session_factory() as session:  # type: ignore[operator]
        total = session.execute(
            select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0))
        ).scalar_one()
        total_calls = session.execute(select(func.count(ModelCall.id))).scalar_one()
        breakdown = session.execute(
            select(
                ModelCall.model,
                ModelCall.agent,
                func.count(ModelCall.id),
                func.coalesce(func.sum(ModelCall.cost_usd), 0.0),
            )
            .group_by(ModelCall.model, ModelCall.agent)
            .order_by(ModelCall.model, ModelCall.agent)
        ).all()

    print(f"\n=== {label}: notional cost if every logical call were fresh ===")
    print(f"  {total_calls} ModelCall rows total, ${total:.4f} notional")
    for model, agent, count, subtotal in breakdown:
        agent_label = agent.value if hasattr(agent, "value") else agent
        print(f"  {model} [{agent_label}]: {count} calls, ${subtotal:.4f}")


def _cassette_file_count(cassette_dir: Path) -> int:
    if not cassette_dir.exists():
        return 0
    return len(list(cassette_dir.glob("*.json")))


def _report_section_statuses(report: object, label: str) -> None:
    """Print each content-dependent section's `MeasurementStatus` --
    specifically so `PARTIALLY_MEASURED` (PROJECT_SPEC.md §M6 Deviation 11)
    is visible before anyone decides whether to commit these cassettes, not
    just the notional-cost/cassette-count numbers `_report_notional_cost`
    already prints.
    """
    from sul.validity.model import ValidityReportModel

    assert isinstance(report, ValidityReportModel)
    print(f"\n=== {label}: section statuses ===")
    for name, section in (
        ("discriminative_validity", report.discriminative_validity),
        ("acquiescence_bias", report.acquiescence_bias),
        ("position_bias", report.position_bias),
        ("known_answer_calibration", report.known_answer_calibration),
    ):
        subjects = ""
        if section.status != section.status.MEASURED and hasattr(
            section, "subjects_attempted"
        ):
            attempted = getattr(section, "subjects_attempted", None)
            measured = getattr(section, "subjects_measured", None)
            if attempted is not None and measured is not None:
                subjects = f" ({measured}/{attempted} subjects)"
        reason = f" -- {section.reason}" if section.reason else ""
        print(f"  {name}: {section.status.value}{subjects}{reason}")


async def main(db_path: Path, max_cost_usd: float) -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY not resolved via Settings")

    cassette_dir = settings.cassette_dir
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)

    print(f"max_cost_usd per check: ${max_cost_usd:.2f} (see --help)")

    before_a = _cassette_file_count(cassette_dir)
    print("=== Config A: Sonnet Analyst, Haiku persona/moderator/probes ===")
    report_a = await run_validity_harness(
        session_factory,
        provider=_make_provider(settings.anthropic_api_key, cassette_dir),
        provider_name="anthropic",
        model=HAIKU,
        model_by_agent={AgentRole.ANALYST: SONNET},
        base_path=REPO_ROOT,
        max_cost_usd=max_cost_usd,
    )
    after_a = _cassette_file_count(cassette_dir)
    _report_notional_cost(session_factory, "Config A")
    _report_section_statuses(report_a, "Config A")

    print("\n=== Config B: Haiku throughout ===")
    report_b = await run_validity_harness(
        session_factory,
        provider=_make_provider(settings.anthropic_api_key, cassette_dir),
        provider_name="anthropic",
        model=HAIKU,
        base_path=REPO_ROOT,
        max_cost_usd=max_cost_usd,
    )
    after_b = _cassette_file_count(cassette_dir)
    _report_notional_cost(session_factory, "Combined (A + B)")
    _report_section_statuses(report_b, "Config B")

    print("\n=== Real network calls (new cassette files written) ===")
    print(f"  Config A: {after_a - before_a} new cassettes")
    print(
        f"  Config B: {after_b - after_a} new cassettes "
        "(expected: Analyst-on-Haiku only -- everything else replayed)"
    )
    print(f"  Total cassette files on disk: {after_b}")

    print(f"\nDb: {db_path}")
    print(f"Cassettes: {cassette_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(tempfile.gettempdir()) / "sul_validity_recording.db",
        help="SQLite file for this recording pass's studies (default: a "
        "temp-dir scratch file, never the project's sul.db).",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=1.0,
        help="Per-check budget ceiling (PROJECT_SPEC.md §M6 Deviation 11 -- "
        "'per-check', not a shared whole-harness total: discriminative "
        "validity spends it twice, once per artefact study, and acquiescence/"
        "position bias each get their own). Default $1.00 is ~10x the "
        "observed real cost of a full artefact study on this 5-persona panel "
        "($0.05-0.11) -- generous enough not to block a legitimate run, low "
        "enough to actually catch a runaway. Previously unset (unbounded); "
        "that was an oversight, not the intent -- see Deviation 12.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.db_path, args.max_cost_usd))
