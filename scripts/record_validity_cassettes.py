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


async def main(db_path: Path) -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY not resolved via Settings")

    cassette_dir = settings.cassette_dir
    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)

    before_a = _cassette_file_count(cassette_dir)
    print("=== Config A: Sonnet Analyst, Haiku persona/moderator/probes ===")
    await run_validity_harness(
        session_factory,
        provider=_make_provider(settings.anthropic_api_key, cassette_dir),
        provider_name="anthropic",
        model=HAIKU,
        model_by_agent={AgentRole.ANALYST: SONNET},
        base_path=REPO_ROOT,
    )
    after_a = _cassette_file_count(cassette_dir)
    _report_notional_cost(session_factory, "Config A")

    print("\n=== Config B: Haiku throughout ===")
    await run_validity_harness(
        session_factory,
        provider=_make_provider(settings.anthropic_api_key, cassette_dir),
        provider_name="anthropic",
        model=HAIKU,
        base_path=REPO_ROOT,
    )
    after_b = _cassette_file_count(cassette_dir)
    _report_notional_cost(session_factory, "Combined (A + B)")

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
    args = parser.parse_args()
    asyncio.run(main(args.db_path))
