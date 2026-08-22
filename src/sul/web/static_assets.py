"""The one vendored third-party asset in this repo: `htmx.min.js`.

PROJECT_SPEC.md §M7 names "Jinja/HTMX" in its own scope bullet
(`FastAPI + Jinja/HTMX dashboard`), but the dashboard must never fetch it
from a CDN at run time -- the container's acceptance criterion is a
`docker run --network none` dashboard, and a `<script src="https://...">`
would silently defeat that the moment someone opened the page without
egress. Vendoring is the only option that satisfies both constraints: the
scope bullet, and run-time network independence.

The file is fetched once, by hand, on the host -- never at image build time,
which would just relocate the same CDN dependency into the Dockerfile.
`HTMX_VERSION`/`HTMX_SHA256` are the pin: `tests/test_vendored_assets.py`
hashes the committed file and asserts both, so a future edit that touches
`src/sul/web/static/htmx.min.js` without updating this file fails loudly
rather than silently shipping an unpinned, unverified blob.

Provenance: fetched from `https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js`
and cross-checked byte-for-byte against
`https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js` (two
independent CDNs serving the same npm-published artefact, same sha256) --
not a single-source download taken on faith.
"""

from __future__ import annotations

HTMX_VERSION = "2.0.4"
HTMX_SHA256 = "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447"
HTMX_FILENAME = "htmx.min.js"

__all__ = ["HTMX_FILENAME", "HTMX_SHA256", "HTMX_VERSION"]
