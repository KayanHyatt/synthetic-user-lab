"""Standalone script, run as a subprocess with a fresh in-memory database:
replays PROJECT_SPEC.md §M6's real cassette recording (`tests/cassettes/`,
Config A -- Persona/Moderator/probes on `claude-haiku-4-5`, Analyst on
`claude-sonnet-5`, Deviation 12/13) and renders the validity report. Mirrors
`tests/support/run_report_script.py`'s pattern for `sul.report`, applied to
`sul.validity`: clustering's own iteration-order sensitivity (documented in
`sul.analysis.clustering`) is exercised here too, since §M6.2's
discriminative-validity check clusters real Analyst findings from these
cassettes, not synthetic ones -- a same-process "render twice" check
couldn't catch that class of defect any better here than it could for
`sul.report`.

Two invocations of this script under different `PYTHONHASHSEED` values must
print byte-identical output. `record=False`: this never touches the network
and never writes a cassette -- a miss here is a hard `CassetteMissError`,
not a silent live dispatch.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from sul.db import make_engine, make_session_factory  # noqa: E402
from sul.enums import AgentRole  # noqa: E402
from sul.models import Base  # noqa: E402
from sul.providers.anthropic import AnthropicProvider  # noqa: E402
from sul.providers.cassette import CassetteTransport  # noqa: E402
from sul.validity.harness import run_validity_harness  # noqa: E402
from sul.validity.markdown import render_validity_markdown  # noqa: E402

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"


async def _main() -> None:
    engine = make_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    transport = CassetteTransport(
        httpx.AsyncHTTPTransport(),
        REPO_ROOT / "tests" / "cassettes",
        record=False,
    )
    # The key never leaves this process -- record=False means replay only,
    # so no request is ever actually sent with it.
    provider = AnthropicProvider("replay-only-sentinel-key", transport=transport)

    report = await run_validity_harness(
        session_factory,
        provider=provider,
        provider_name="anthropic",
        model=HAIKU,
        model_by_agent={AgentRole.ANALYST: SONNET},
        base_path=REPO_ROOT,
    )

    print(
        json.dumps(
            {
                "markdown": render_validity_markdown(report),
                "statuses": {
                    "discriminative_validity": (
                        report.discriminative_validity.status.value
                    ),
                    "acquiescence_bias": report.acquiescence_bias.status.value,
                    "position_bias": report.position_bias.status.value,
                    "known_answer_calibration": (
                        report.known_answer_calibration.status.value
                    ),
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
