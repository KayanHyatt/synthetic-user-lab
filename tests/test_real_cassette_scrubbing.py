"""M2's cassette scrubber (`sul.providers.cassette.scrub_headers`) had, until
the M6 two-configuration recording pass, only ever been proven against a
`MockTransport` recording (`tests/test_cassettes.py`) -- synthetic headers,
never a real `x-api-key` sent to the real Anthropic API. This scans whatever
real cassette bytes are committed in `tests/cassettes/` (written by
`scripts/record_validity_cassettes.py`) for exactly what a leaked credential
would look like there: the header names by name, the `sk-ant-` prefix, and
-- when a real key is available to check against, via `ANTHROPIC_API_KEY` --
the literal key value as a substring. No network call; reads only files
already on disk, so this stays offline (CLAUDE.md) regardless of whether a
key is configured.

`_real_cassette_files()` globs `tests/cassettes/` fresh every time this file
runs -- every assertion below is checked against whatever is actually
committed there at test-run time, never a fixed snapshot recorded in this
docstring. That matters because this file has already gone vacuous once
without anyone noticing: an earlier recording pass found real Haiku's
structured output too unreliable to produce a usable recording and its 26
cassettes were deleted rather than committed, leaving `tests/cassettes/`
empty for several commits while this file kept reporting "passed" against
zero files. As of PROJECT_SPEC.md §M6 Deviations 12/13/18, the directory
holds real recorded traffic (Config A + Config B) and these assertions run
for real; if it is ever emptied again, they will silently go back to being
vacuously true rather than fail loudly -- a limitation of iterating a glob
with no minimum-count check, not fixed by this docstring alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sul.config import get_settings

CASSETTE_DIR = Path(__file__).resolve().parents[1] / "tests" / "cassettes"


def _real_cassette_files() -> list[Path]:
    if not CASSETTE_DIR.exists():
        return []
    return sorted(CASSETTE_DIR.glob("*.json"))


def test_committed_cassettes_contain_no_credential_headers() -> None:
    for path in _real_cassette_files():
        raw = path.read_text(encoding="utf-8")
        lower = raw.lower()
        for header_name in ("x-api-key", "authorization"):
            assert header_name not in lower, (
                f"{path.name} contains the header name {header_name!r}"
            )


def test_committed_cassettes_contain_no_anthropic_key_prefix() -> None:
    for path in _real_cassette_files():
        raw = path.read_text(encoding="utf-8")
        assert "sk-ant-" not in raw, f"{path.name} contains an 'sk-ant-' prefix"


def test_committed_cassettes_do_not_contain_the_configured_key() -> None:
    """Only meaningful when a real key is configured (this repo's own rule,
    `.env.example`: "The full test suite must pass with none of the
    *_API_KEY values set") -- skipped, not failed, when absent.
    """
    key = get_settings().anthropic_api_key
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not configured; nothing to check against")
    for path in _real_cassette_files():
        raw = path.read_text(encoding="utf-8")
        assert key not in raw, f"{path.name} contains the configured API key"
