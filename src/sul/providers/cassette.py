"""Record/replay of real provider HTTP traffic, scrubbed at write time.

The cassette transport wraps a real async HTTP transport and sits *inside*
an SDK client's transport, not inside `FakeProvider` — a cassette recorder
is a decorator over a real provider, a synthesiser is a leaf, and the two
use genuinely different keys (see the M2 implementation note in
PROJECT_SPEC.md). Because it operates at the HTTP layer, the same logic
works for every adapter without each one having to know about cassettes.

Scrubbing happens *before* a byte reaches disk (CLAUDE.md: "No secrets in
the repo"), not as a read-time filter — a credential redacted only on
replay would still sit in the cassette file in plaintext.

Two thin wrapper classes are exported because two different httpx major
versions are in play in this dependency tree: Anthropic and google-genai's
SDKs take a plain `httpx.AsyncClient`, while the OpenAI SDK (3.x) vendors
its own httpx fork, importable as `httpx2`, and requires an
`httpx2.AsyncClient` / `httpx2.AsyncBaseTransport`. Both flavours expose an
identical `Request`/`Response`/`Headers`/`URL` surface at runtime, so
`CassetteCore` below implements the record/replay/scrub logic once, against
that duck-typed surface, and each wrapper only supplies its module's
`Response` class to replay against.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from sul.providers.base import ProviderError

_SENSITIVE_PATTERN = re.compile(r"key|token|secret|auth", re.IGNORECASE)
_ALWAYS_SENSITIVE_HEADERS = {"cookie", "set-cookie"}
_REDACTED = "<redacted>"


class CassetteMissError(ProviderError):
    """Raised on replay when no cassette matches the request.

    Never falls through to the network — a miss is a hard failure, not an
    implicit "record now" (that requires the caller to opt in explicitly via
    `record=True` / `RECORD=1`).
    """

    def __init__(self, key: str, path: Path) -> None:
        self.key = key
        self.path = path
        super().__init__(
            f"No cassette for key {key!r} at {path} (offline replay only)."
        )


def _is_sensitive_name(name: str) -> bool:
    lname = name.lower()
    return lname in _ALWAYS_SENSITIVE_HEADERS or bool(_SENSITIVE_PATTERN.search(lname))


def scrub_headers(headers: Any) -> dict[str, str]:
    """Drop every credential-bearing header entirely, by name, in either direction.

    Dropped rather than value-redacted: a test that scans the raw cassette
    file text for header *names* (`x-api-key`, `Authorization`, ...) must
    find none, and `{"x-api-key": "<redacted>"}` would still contain the
    literal string `"x-api-key"`.
    """
    return {k: v for k, v in headers.items() if not _is_sensitive_name(k)}


# Headers describing the *wire* representation of a response
# (PROJECT_SPEC.md §M6 Deviation 13): `_write` always stores `response.text`
# -- httpx's already-decompressed body -- never the raw wire bytes, so a
# recorded `content-encoding` (e.g. `gzip`, what every real Anthropic
# response arrives as) is stale the moment it's written, and describes a
# transformation that was already undone. Replaying a cassette that still
# claims `content-encoding: gzip` over already-plaintext content makes
# httpx/the `anthropic` SDK try to gzip-decompress plaintext -- surfacing,
# opaquely, as `anthropic.APIConnectionError` on every single replay
# (first hit the moment `record=True` ever ran against the real API,
# since every prior cassette test recorded via `httpx.MockTransport`,
# which never sets `content-encoding`). `content-length` and
# `transfer-encoding` are dropped for the same reason -- both describe the
# original (possibly compressed, possibly chunked) wire body, not the
# plaintext this cassette actually stores.
_STALE_RESPONSE_HEADERS = frozenset(
    {"content-encoding", "content-length", "transfer-encoding"}
)


def drop_stale_response_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        k: v for k, v in headers.items() if k.lower() not in _STALE_RESPONSE_HEADERS
    }


def scrub_url(url: Any) -> Any:
    """Redact sensitive query params (e.g. Gemini's `?key=...`)."""
    if not url.params:
        return url
    scrubbed = [
        (k, _REDACTED if _is_sensitive_name(k) else v)
        for k, v in url.params.multi_items()
    ]
    return url.copy_with(params=scrubbed)


def _canonical_body(content: bytes) -> bytes:
    """Canonicalise a JSON body so key ordering never affects the match key.

    Same canonicalisation `sul.hashing.config_hash` uses
    (`json.dumps(sort_keys=True, separators=(",", ":"))`); duplicated here
    rather than imported because the body may not be a JSON *object* (a
    `Mapping`), while `config_hash`'s signature requires one. Non-JSON or
    unparseable bodies are hashed as their raw bytes.
    """
    if not content:
        return content
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return content
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def match_key(method: str, url: Any, body: bytes) -> str:
    """The cassette lookup key: method + scrubbed URL + canonicalised body.

    Scrubbing happens *before* the key is computed — a scrubbed cassette must
    still replay, and it only can if the same scrub is applied on both the
    write path and the read path. Headers are deliberately excluded: they
    carry the credentials that just got scrubbed, so keying on them would
    make a scrubbed cassette unmatchable against a fresh (unscrubbed) replay
    request.
    """
    scrubbed_url = str(scrub_url(url))
    canonical = _canonical_body(body)
    payload = b"|".join(
        [method.upper().encode("utf-8"), scrubbed_url.encode("utf-8"), canonical]
    )
    return hashlib.sha256(payload).hexdigest()


class CassetteCore:
    """Record/replay implementation shared by both httpx-flavoured wrappers.

    Operates on duck-typed request/response objects (`Any`) because it must
    work identically against `httpx.Request`/`Response` and
    `httpx2.Request`/`Response` — two distinct classes with an identical
    runtime surface. `response_cls` is whichever module's `Response` the
    calling transport must hand back.

    `record_if_missing` (default `False`, so every existing call site is
    unaffected) only matters when `record=True`: instead of unconditionally
    re-dispatching and overwriting, a key that already has a cassette on
    disk is replayed from it, and only a genuine miss reaches the network
    and writes a new file. This is what lets a second recording pass share
    a cassette directory with a first one — requests whose key is unchanged
    (same model, same prompt, same everything the key is built from) cost
    nothing the second time; only genuinely new keys (e.g. one agent's model
    changed) are actually dispatched.
    """

    def __init__(
        self,
        inner: Any,
        cassette_dir: Path,
        *,
        record: bool,
        response_cls: Callable[..., Any],
        record_if_missing: bool = False,
    ) -> None:
        self._inner = inner
        self._cassette_dir = cassette_dir
        self._record = record
        self._response_cls = response_cls
        self._record_if_missing = record_if_missing

    async def handle(self, request: Any) -> Any:
        body = await request.aread()
        key = match_key(request.method, request.url, body)
        path = self._cassette_dir / f"{key}.json"

        if self._record:
            if self._record_if_missing and path.exists():
                return self._load(path, request)
            response = await self._inner.handle_async_request(request)
            await response.aread()
            self._write(path, request, response, body)
            return response

        if not path.exists():
            raise CassetteMissError(key, path)
        return self._load(path, request)

    def _write(self, path: Path, request: Any, response: Any, body: bytes) -> None:
        cassette = {
            "request": {
                "method": request.method,
                "url": str(scrub_url(request.url)),
                "headers": scrub_headers(request.headers),
                "body": body.decode("utf-8", errors="replace"),
            },
            "response": {
                "status_code": response.status_code,
                "headers": drop_stale_response_headers(scrub_headers(response.headers)),
                "body": response.text,
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        # Trailing newline: pre-commit's end-of-file-fixer hook rewrites any
        # committed file that lacks one, so a cassette written without it
        # gets silently reformatted on the next commit that touches it --
        # cost a whole commit attempt once already (PROJECT_SPEC.md §M6
        # Deviation 18).
        path.write_text(
            json.dumps(cassette, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _load(self, path: Path, request: Any) -> Any:
        cassette = json.loads(path.read_text(encoding="utf-8"))
        resp = cassette["response"]
        return self._response_cls(
            status_code=resp["status_code"],
            headers=resp["headers"],
            content=resp["body"].encode("utf-8"),
            request=request,
        )


class CassetteTransport(httpx.AsyncBaseTransport):
    """Cassette transport for SDKs built on plain `httpx` (Anthropic, Gemini)."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        cassette_dir: Path,
        *,
        record: bool = False,
        record_if_missing: bool = False,
    ) -> None:
        self._core = CassetteCore(
            inner,
            cassette_dir,
            record=record,
            response_cls=httpx.Response,
            record_if_missing=record_if_missing,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response: httpx.Response = await self._core.handle(request)
        return response


__all__ = [
    "CassetteCore",
    "CassetteMissError",
    "CassetteTransport",
    "drop_stale_response_headers",
    "match_key",
    "scrub_headers",
    "scrub_url",
]
