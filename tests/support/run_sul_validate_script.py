"""Standalone script, run as a subprocess: invokes `sul validate` exactly as
a user would (PROJECT_SPEC.md §M6 Deviation 5, amended) and prints the
resulting `docs/validity_report.md` content. Mirrors
`tests/support/run_report_script.py`'s cross-process pattern for
`sul.report`, applied to the real CLI command itself rather than a
hand-rolled reimplementation of its provider-selection logic -- there is
exactly one place that decides between a cassette-backed `AnthropicProvider`
and `FakeProvider` (`sul.cli._select_validate_provider`), and this script
goes through it, not around it.

Uses the real, default `settings.cassette_dir` (`tests/cassettes/`, 46
committed cassettes -- PROJECT_SPEC.md §M6 Deviation 12/13) unmodified: the
point of this script is to prove `sul validate`'s actual default behaviour
against what is actually committed, byte for byte. Only `SUL_DATABASE_URL`
is redirected, to a fresh temp-dir database, so this never touches the
project's own `sul.db`.

Two invocations of this script under different `PYTHONHASHSEED` values must
print byte-identical output.

Also reports `failed_run_count`/`failed_run_errors` (mirroring
`run_config_b_validity_report_script.py`'s own completeness check, added
the same session once that script proved a "measured" section status alone
doesn't prove every needed cassette was present -- `_run_one_persona`'s
per-run containment, PROJECT_SPEC.md §M7 Deviation 17, can absorb a single
missing/failed dispatch into one `FAILED` `Run` row without necessarily
changing a section's aggregate output or its status). Before this, these
two tests were protected against a missing Config A cassette only
incidentally, by the byte-comparison against the committed
`docs/validity_report.md` -- this makes that protection explicit.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from sul import models  # noqa: E402
from sul.cli import app  # noqa: E402
from sul.config import get_settings  # noqa: E402
from sul.db import make_engine, make_session_factory  # noqa: E402
from sul.enums import RunStatus  # noqa: E402


def _main() -> None:
    # Not tempfile.TemporaryDirectory(): `validate()` (sul.cli) never
    # disposes the SQLAlchemy engine it creates around `db_path`, and this
    # script runs it in-process (via CliRunner, not a further subprocess),
    # so the sqlite3 file handle is still open when a `with`-block cleanup
    # would try to delete it -- fatal on Windows (`PermissionError:
    # [WinError 32]`), silently fine on POSIX. A plain `mkdtemp()` scratch
    # dir, left for the OS to reclaim, matches
    # `scripts/record_validity_cassettes.py --db-path`'s own precedent for
    # exactly this class of short-lived scratch database.
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "sul.db"
    out_dir = Path(tmp) / "docs"

    os.environ["SUL_DATABASE_URL"] = f"sqlite:///{db_path}"
    get_settings.cache_clear()

    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--out-dir", str(out_dir)])
    if result.exit_code != 0:
        raise SystemExit(f"sul validate exited {result.exit_code}: {result.output}")

    markdown = (out_dir / "validity_report.md").read_text(encoding="utf-8")

    # A fresh engine/session against the same file-backed db_path -- safe
    # to open alongside validate()'s own still-open one (SQLite supports
    # concurrent readers), and simpler than threading a session_factory
    # through CliRunner's own in-process invocation.
    query_engine = make_engine(f"sqlite:///{db_path}")
    query_session_factory = make_session_factory(query_engine)
    with query_session_factory() as session:
        failed_runs = (
            session.execute(
                select(models.Run).where(models.Run.status == RunStatus.FAILED)
            )
            .scalars()
            .all()
        )

    print(
        json.dumps(
            {
                "markdown": markdown,
                "failed_run_count": len(failed_runs),
                "failed_run_errors": [r.error for r in failed_runs],
            }
        )
    )


if __name__ == "__main__":
    _main()
