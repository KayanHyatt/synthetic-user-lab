# Working agreement

## Stack
Python 3.12. FastAPI, SQLAlchemy 2.x, Pydantic v2, Typer (CLI), pytest, ruff,
SQLite. Frontend: Jinja2 + HTMX (upgrade to React only if the dashboard
genuinely needs client state). Docker + docker-compose.

## Rules
- Tests must run fully offline. No test may hit a real LLM API, ever.
- No secrets in the repo. Config via `.env` + `.env.example`.
- Every LLM call goes through the provider abstraction. No direct SDK calls in
  business logic.
- Structured LLM output is parsed into Pydantic models. Never regex an LLM
  response.
- Type hints on everything public. `ruff check` and `ruff format` clean.
- One milestone per session. Stop at the milestone boundary and report.
- If a milestone's acceptance criteria cannot be met as written, stop and say
  so rather than redefining them.

## Commands

This project targets native Windows + PowerShell, with Python and
dependencies managed entirely by **uv** (`uv venv`, `uv add`, `uv run`) — never
`pip install` or a system Python.

`make` is not installed on this machine. `make.ps1` at the repo root provides
the same targets; run it as `.\make.ps1 <target>`:

```
.\make.ps1 install   # uv sync + install pre-commit hooks
.\make.ps1 check     # ruff check + ruff format --check + mypy + pytest
.\make.ps1 test      # pytest only
.\make.ps1 demo      # runs a complete study with FakeProvider, no API key (M7)
.\make.ps1 validate  # runs the M6 validity harness, writes docs/validity_report.md
```

## Environment notes
- TLS: `SSL_CERT_FILE` pointed at a Windows root-store export
  (`windows-roots.pem`) worked first try against the real Anthropic API —
  `httpx`/`anthropic`/`certifi` needed no extra configuration. If a future
  session hits an SSL verification error, look at whether `SSL_CERT_FILE` is
  still set and pointing at a valid file before assuming it's a code issue.
