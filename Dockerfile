# syntax=docker/dockerfile:1
#
# PROJECT_SPEC.md §M7 packaging. Builds the read-only dashboard image; the
# acceptance chain is `docker compose up` -> `.\make.ps1 demo` (on the
# host, against a bind-mounted `sul.db` -- see docker-compose.yml) ->
# reload the dashboard. This image ships no `tests/cassettes/`
# (.dockerignore excludes them), so it cannot run `sul validate` --
# `sul.cli._select_validate_provider` would silently fall back to
# FakeProvider rather than replaying Config A, which would be worse than
# not offering the command at all. What it can do: serve the dashboard,
# and run `sul demo` (constructs `FakeProvider()` directly, needs no
# cassettes -- PROJECT_SPEC.md §M7 5.4).
#
# Both base images are pinned by digest, not a floating tag (resolved this
# session, recorded in PROJECT_SPEC.md's §M7 deviation).

FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS base

# ---------------------------------------------------------------------------
# Builder stage: resolves nothing (`uv sync --frozen` against the committed
# uv.lock) and never reaches the runtime image -- its only job is to
# populate /app/.venv.
# ---------------------------------------------------------------------------
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

WORKDIR /app

# pyproject.toml + uv.lock first for layer caching; src/ is needed too --
# hatchling's editable install (uv sync's default for a project, not just
# its dependencies) reads src/sul at sync time and records this exact
# absolute path, which is why the runtime stage below copies src/ back to
# this same /app/src location rather than anywhere else.
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# Runtime stage: no build tooling, no uv, no network needed at all --
# FakeProvider has no transport and the dashboard is strictly read-only
# (enforced at the AST level, tests/test_agent_module_hygiene.py).
# ---------------------------------------------------------------------------
FROM base AS runtime

RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --no-create-home appuser

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY configs ./configs
COPY artefacts ./artefacts

# 0.0.0.0, not the Settings default of 127.0.0.1 -- inside a container the
# loopback default would leave docker-compose's published port unreachable.
# Config-driven (PROJECT_SPEC.md §M7's Settings.dashboard_host groundwork),
# not a code change.
ENV PATH="/app/.venv/bin:${PATH}" \
    SUL_DASHBOARD_HOST=0.0.0.0 \
    SUL_DASHBOARD_PORT=8000

USER appuser
EXPOSE 8000

ENTRYPOINT ["/app/.venv/bin/sul"]
CMD ["dashboard"]
