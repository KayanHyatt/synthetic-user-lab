"""Shared helper for `sul.web` dashboard tests: an in-process ASGI client
over `sul.web.app.create_app()`.

PROJECT_SPEC.md §M7 5.7: in-process ASGI transport, never a bound port and
never a socket-guard exemption (`tests/conftest.py` is untouched by this
project's dashboard tests). `httpx.ASGITransport` patches nothing global --
it only short-circuits *this client's own* requests into the app in-process
-- so it cannot mask a real provider dispatch: if a handler ever reached a
real adapter, that adapter's own `httpx` client would still attempt a
non-loopback connection and trip the session-scoped guard in
`tests/conftest.py::_block_network`. (`sul.web`'s AST hygiene test,
`tests/test_agent_module_hygiene.py::test_web_modules_cannot_dispatch_an_llm_call`,
is the structural half of that guarantee; this is the runtime half.)

A fresh `create_app()` per call, since `Settings.database_url` is re-read
inside each request handler (see `sul.web.app.create_app`'s docstring) --
callers set `SUL_DATABASE_URL` and clear `get_settings`'s cache before
opening a client.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from sul.web.app import create_app


@asynccontextmanager
async def dashboard_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://dashboard.test"
    ) as client:
        yield client


__all__ = ["dashboard_client"]
