"""Standalone script, run as a subprocess, for the M4 acceptance test's "kill
the process at 50%" clause (PROJECT_SPEC.md §M4).

An in-process simulated exception (raised mid-`asyncio.gather`) can leave a
straggling `asyncio.to_thread` write in flight -- cancelling the *awaiting*
coroutine does not stop the underlying OS thread already dispatched to the
executor, so that write can land arbitrarily late, even after a later
`run_study` call in the same process has already cleared and started
rewriting the same rows. A real killed process doesn't have this problem
(everything in it, including any half-finished thread, simply stops
existing) -- so this script reproduces "kill the process" as literally as an
offline test can: it runs in its own OS process, against a file-backed
SQLite database (not `:memory:`, so state survives the process), and calls
`os._exit()` -- not `sys.exit()`, not a raised exception -- once a call
threshold is reached, terminating unconditionally with no unwind, no
`finally` blocks, no chance for anything still in flight to complete.

Usage:
    python run_study_script.py <db_path> <state_path> [--crash-after N]

`state_path` is a small JSON sidecar recording the materialised study's ids,
written on the first invocation and reused (not re-materialised) by later
invocations against the same `db_path` -- exactly how a real resume would
look up "the study already in progress" rather than creating a second one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy.pool import StaticPool  # noqa: E402

from sul.db import make_engine, make_session_factory  # noqa: E402
from sul.models import Base  # noqa: E402
from sul.providers.base import (  # noqa: E402
    Completion,
    LLMProvider,
    Message,
)
from sul.providers.fake import FakeProvider  # noqa: E402
from sul.runner.orchestrator import run_study  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
from tests.support.study_factory import build_materialized_study  # noqa: E402


class _CrashAfterN:
    """`os._exit()`, not an exception: the whole point is that nothing after
    this line -- in this process -- ever runs again.
    """

    def __init__(self, inner: LLMProvider, n: int) -> None:
        self._inner = inner
        self._n = n
        self._count = 0

    async def complete(
        self,
        *,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int,
        seed: int | None,
        response_schema: object | None = None,
    ) -> Completion:
        self._count += 1
        if self._count >= self._n:
            sys.stderr.write(f"SIMULATED KILL at call {self._count}\n")
            sys.stderr.flush()
            os._exit(137)  # 128 + SIGKILL, matching a real killed process
        return await self._inner.complete(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            response_schema=response_schema,  # type: ignore[arg-type]
        )


async def _main(db_path: str, state_path: str, crash_after: int | None) -> None:
    engine = make_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    state_file = Path(state_path)
    if state_file.exists():
        ids = json.loads(state_file.read_text(encoding="utf-8"))
        study_id, scenario_id = ids["study_id"], ids["scenario_id"]
    else:
        materialized = build_materialized_study(session_factory)
        study_id, scenario_id = materialized.study_id, materialized.scenario_id
        state_file.write_text(
            json.dumps({"study_id": study_id, "scenario_id": scenario_id}),
            encoding="utf-8",
        )

    provider: LLMProvider = FakeProvider()
    if crash_after is not None:
        provider = _CrashAfterN(FakeProvider(), crash_after)

    await run_study(
        session_factory,
        study_id=study_id,
        scenario_id=scenario_id,
        provider=provider,
        provider_name="fake",
        model="fake-1",
    )
    print("DONE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("state_path")
    parser.add_argument("--crash-after", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(_main(args.db_path, args.state_path, args.crash_after))
