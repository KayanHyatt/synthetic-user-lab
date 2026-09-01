"""Standalone script, run as a subprocess: builds Config B (Analyst also on
Haiku -- PROJECT_SPEC.md §M6 Deviation 18) by construction and calls
`run_validity_harness` directly, printing the four gated sections' actual
values as JSON.

Config B is structurally unreachable from `sul validate`:
`sul.cli._select_validate_provider` always constructs its replay-only
provider with `_CASSETTE_CONFIG_MODEL`/`_CASSETTE_CONFIG_ANALYST_MODEL`
(Config A's own combination), regardless of what else is committed in
`tests/cassettes/` -- so there is no CLI command, and therefore no
`CliRunner`-driven script in this style, that could produce Config B's
report the way `run_sul_validate_script.py` produces Config A's. This
script goes around the CLI on purpose: it builds the same kind of
replay-only `AnthropicProvider` `_select_validate_provider` builds (a
`CassetteTransport(record=False)` over the real, committed
`tests/cassettes/`), but passes `model="claude-haiku-4-5"` and no
`model_by_agent` at all -- Config B by construction, not by argument
parsing. `record=False` means a cassette miss raises `CassetteMissError`
rather than dispatching to the network (`sul/providers/cassette.py`,
`CassetteCore.handle`'s `if not path.exists(): raise CassetteMissError`
branch -- the `record=True` branch that would touch `self._inner`, the
wrapped real transport, is never reached at all).

**A "measured" section status alone does not prove every cassette this run
needed was present, and this script does not claim otherwise.** Verified
by hand while building this script: hiding one genuinely-needed Config B
cassette still produced `discriminative_validity: measured`, byte-for-byte
identical headline numbers, and exit code 0. `CassetteMissError` is a
`ProviderError` subclass; `anthropic`'s own client wraps whatever the
transport raises as `APIConnectionError("Connection error.")` before
`sul.providers.anthropic.AnthropicProvider.complete` re-raises it as a
bare `ProviderError` -- the original `CassetteMissError` message (which
key, which path) never survives past that point, only `__cause__` does.
That `ProviderError` then hits `_run_one_persona`'s own per-run
containment (PROJECT_SPEC.md §M7 Deviation 17): the one affected persona's
`Run` is marked `FAILED` with the generic "Connection error." message,
but the section it belongs to keeps going on its remaining personas and
can still land on `measured` if the missing persona's own finding
wouldn't have changed the aggregate anyway -- which is exactly what
happened in the hand-verification above (the hidden cassette's finding
was categorised `delight`, contributing nothing to the blocker/confusion
count either way). This is a real, general interaction between per-run
error containment and cassette completeness, not specific to this
script.

Completeness is therefore checked directly instead: after
`run_validity_harness` returns, every `Run` row written to this run's own
throwaway database is queried for `status == RunStatus.FAILED`, and the
count (with each row's `error`) is included in the payload alongside the
section values. A clean report with zero failed `Run` rows is what
actually proves the 10 Config B cassettes are complete, not the section
statuses by themselves.

Uses the real, default cassette directory (`tests/cassettes/`) unmodified,
pinned by path rather than imported from `sul.config.Settings` --
`tests/test_docs_claims.py::CASSETTE_DIR` does the same, for the same
reason: this script's provider choice must not silently move if some
future session changes a default elsewhere. Only the database is
redirected, to a fresh temp-dir file, so this never touches the project's
own `sul.db`.

Discriminative validity (and the known-answer calibration derived from
it) clusters real Analyst findings -- `sul.analysis.clustering`'s own
module docstring documents this as order-sensitive. Two invocations of
this script under different `PYTHONHASHSEED` values must print
byte-identical output before any single run's numbers are trusted
(mirrors `run_sul_validate_script.py`'s own cross-process pattern, for
the same reason).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
CASSETTE_DIR = REPO_ROOT / "tests" / "cassettes"
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from sul import models  # noqa: E402
from sul.db import create_all, make_engine, make_session_factory  # noqa: E402
from sul.enums import RunStatus  # noqa: E402
from sul.providers.anthropic import AnthropicProvider  # noqa: E402
from sul.providers.cassette import CassetteTransport  # noqa: E402
from sul.validity.harness import run_validity_harness  # noqa: E402

# Config B: everything on Haiku, including the Analyst -- no model_by_agent
# override at all. See scripts/record_validity_cassettes.py's own docstring
# for what this means in practice: every Persona/Moderator/probe request is
# byte-identical to Config A's and replays from the same cassette files;
# only the Analyst requests differ (a different `model` field in the
# canonicalised body -- sul/providers/cassette.py::match_key), and those are
# the 10 cassettes Deviation 18 recorded.
_MODEL = "claude-haiku-4-5"


async def _main_async() -> None:
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "sul.db"

    engine = make_engine(f"sqlite:///{db_path}")
    create_all(engine)
    session_factory = make_session_factory(engine)

    transport = CassetteTransport(
        httpx.AsyncHTTPTransport(), CASSETTE_DIR, record=False
    )
    provider = AnthropicProvider(
        "sul-config-b-replay-only-sentinel-key", transport=transport
    )

    report = await run_validity_harness(
        session_factory,
        provider=provider,
        provider_name="anthropic",
        model=_MODEL,
        base_path=REPO_ROOT,
    )

    with session_factory() as session:
        failed_runs = (
            session.execute(
                select(models.Run).where(models.Run.status == RunStatus.FAILED)
            )
            .scalars()
            .all()
        )

    payload = {
        "provider_name": report.provider_name,
        "model": report.model,
        "discriminative_validity": report.discriminative_validity.model_dump(
            mode="json"
        ),
        "acquiescence_bias": report.acquiescence_bias.model_dump(mode="json"),
        "position_bias": report.position_bias.model_dump(mode="json"),
        "known_answer_calibration": report.known_answer_calibration.model_dump(
            mode="json"
        ),
        "failed_run_count": len(failed_runs),
        "failed_run_errors": [r.error for r in failed_runs],
    }
    print(json.dumps(payload, sort_keys=True))


def _main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    _main()
