"""`src/sul/web/static/htmx.min.js` is the one vendored third-party asset in
this repo (PROJECT_SPEC.md §M7 deviation, `sul.web.static_assets`). Hashes
the committed file against the pinned `HTMX_SHA256` -- a future edit to the
file that doesn't also update the pin fails loudly here, rather than
shipping an unverified blob nobody re-checked.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sul.web.static_assets import HTMX_FILENAME, HTMX_SHA256, HTMX_VERSION

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "sul" / "web" / "static"


def test_htmx_file_is_committed() -> None:
    assert (STATIC_DIR / HTMX_FILENAME).exists()


def test_htmx_file_matches_its_pinned_sha256() -> None:
    raw = (STATIC_DIR / HTMX_FILENAME).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == HTMX_SHA256, (
        f"{HTMX_FILENAME} on disk doesn't match HTMX_SHA256 in "
        "sul.web.static_assets -- if this file was intentionally updated, "
        "update HTMX_VERSION/HTMX_SHA256 to match"
    )


def test_htmx_version_is_pinned() -> None:
    assert HTMX_VERSION


def test_htmx_file_is_not_html_escaped_or_truncated() -> None:
    """A cheap sanity check that this is really the htmx library and not an
    empty file or an HTML error page saved by mistake.
    """
    raw = (STATIC_DIR / HTMX_FILENAME).read_text(encoding="utf-8")
    assert "htmx" in raw.lower()
    assert len(raw) > 10_000
