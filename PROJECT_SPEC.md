# Synthetic User Lab — Build Spec

> **For Claude Code.** Save as `PROJECT_SPEC.md` at repo root. Implement one
> milestone per session. Do not skip ahead. Every milestone ends with the
> acceptance criteria passing and a commit.

---

## 1. What this is

A research harness that runs a **panel of LLM-simulated users** against a
product artefact (a landing page, an onboarding flow, a pricing table, an API's
docs, a survey) and produces a structured, reproducible research report:
findings ranked by severity and frequency, broken down by user segment, with
every claim traceable to a transcript.

An orchestrator coordinates **role-isolated sub-agents**:

- **Moderator** — knows the research goal, asks the persona questions, probes.
  Never speaks in character.
- **Persona** — knows only its own persona card and the artefact. Never sees the
  research goal, the other personas, or what the researcher hopes to hear.
- **Analyst** — sees only completed transcripts. Extracts structured findings.
  Never talks to a persona.

Context isolation is the point, not an implementation detail: a persona that can
see the research question will answer the research question instead of behaving
like a user.

### The honest framing (put this in the README)

Synthetic users do **not** replace real user research. They are a cheap,
fast, reproducible way to generate hypotheses and catch obvious problems before
spending real participants' time. The lab's job is to be explicit about where
that holds — which is what M6 measures. A tool that is honest about its own
limits is a far better portfolio piece than one that overclaims.

### Non-goals

- Not a replacement for real usability testing.
- Not a browser-automation agent that clicks through live sites (v2 idea; keep
  artefacts as text/HTML/screenshot inputs for v1).
- Not a general chat UI.

---

## 2. `CLAUDE.md` (copy into repo root)

```markdown
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
make install / make check / make test / make demo / make validate
```

---

## 3. Repo layout

```
synthetic-user-lab/
├── CLAUDE.md
├── PROJECT_SPEC.md
├── Makefile
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── configs/
│   ├── panel.example.yaml         # persona population definition
│   └── study.example.yaml         # artefact + scenario + panel + budget
├── artefacts/
│   ├── good_onboarding.html       # fixture artefacts for demo + validity tests
│   └── bad_onboarding.html
├── src/sul/
│   ├── models/          # SQLAlchemy ORM
│   ├── schemas/         # Pydantic
│   ├── providers/       # base.py, anthropic.py, openai.py, gemini.py, fake.py
│   ├── personas/        # archetypes, sampler
│   ├── agents/          # moderator.py, persona.py, analyst.py
│   ├── runner/          # orchestrator, budget, retry, resume
│   ├── analysis/        # clustering, ranking, segments
│   ├── validity/        # M6 harness
│   ├── report/          # markdown + html renderers
│   ├── web/             # FastAPI + templates
│   └── cli.py
├── tests/
│   ├── cassettes/       # recorded provider responses
│   └── ...
└── docs/
    ├── architecture.md
    └── limitations.md
```

---

## 4. Milestones

### M0 — Scaffold and guardrails

- `pyproject.toml`, venv, ruff, pytest (with `-m` markers registered), pre-commit.
- `Makefile`: `install`, `check` (lint + typecheck + test), `test`, `demo`, `validate`.
- `.env.example` listing every key the app reads. `.gitignore` covering `.env`, `*.db`, `__pycache__`.
- `CLAUDE.md` written.

**Acceptance:** `make check` green on a fresh clone. `git grep -iE "sk-|api[_-]?key\s*=" -- ':!*.example'` returns nothing.

---

### M1 — Domain model and storage

SQLAlchemy models, SQLite, `create_all` (Alembic optional — if added, it must be
in this milestone, not bolted on later):

| Model | Key fields |
|---|---|
| `Study` | id, name, research_goal, artefact_id, config_hash, created_at, git_sha |
| `Artefact` | id, name, kind (html/text/image), content_hash, body |
| `Panel` | id, study_id, seed, size, config_yaml |
| `Persona` | id, panel_id, name, segment, attributes (JSON), card_text |
| `Scenario` | id, study_id, task, questions (JSON) |
| `Run` | id, study_id, persona_id, scenario_id, status, started_at, finished_at, error |
| `Turn` | id, run_id, role, ordinal, content, model_call_id |
| `ModelCall` | id, run_id, agent, provider, model, prompt_hash, tokens_in, tokens_out, cost_usd, latency_ms, seed, cached |
| `Finding` | id, run_id, category, severity(1-5), summary, evidence_turn_id, cluster_id |

`ModelCall` is what makes cost and reproducibility auditable — do not treat it
as optional bookkeeping.

> **M1 implementation note.** Columns added beyond this table, and why:
> `Study.research_goal` is the string the persona-isolation boundary must
> never leak — without it there is nothing for the M4 isolation test to
> assert against. `Study.artefact_id` links a study to the artefact it runs
> against (the table above never otherwise connects them, and M6's
> discriminative-validity check needs exactly this edge).
> `Artefact.name` is a human-readable label, since `content_hash` isn't one.
> `Run.error` carries a failed run's failure reason (`status` alone cannot).
> `ModelCall.run_id` (nullable) and `ModelCall.agent` exist because the
> Analyst writes `ModelCall` rows with no corresponding `Turn` — without
> `run_id` here, `sul cost <study_id>` (M2's acceptance criterion) would
> silently miss Analyst spend. No `Evidence` table and no Alembic were added;
> both remain out of scope for M1.

**Acceptance:** tests create a full object graph and query it; `docs/architecture.md` contains an ER diagram (Mermaid is fine).

---

### M2 — Provider abstraction + FakeProvider

```python
class LLMProvider(Protocol):
    async def complete(
        self, *, messages: list[Message], model: str,
        temperature: float, max_tokens: int, seed: int | None,
        response_schema: type[BaseModel] | None = None,
    ) -> Completion: ...
```

- Adapters: Anthropic, OpenAI, Gemini. Each maps its own errors to a shared
  `ProviderError` hierarchy (`RateLimited`, `Overloaded`, `BadRequest`, `Refused`).
- `FakeProvider`: deterministic, keyed on `sha256(model + prompt + seed)`,
  reading from `tests/cassettes/`. A `RECORD=1` env var records real responses
  into cassettes; default replays.
- Every call writes a `ModelCall` row with token counts and cost, using a
  per-model price table in `configs/pricing.yaml`.
- Structured output: pass a Pydantic schema, validate, and on failure run **one**
  repair turn ("your output failed validation, here is the error") before giving up.

> **M2 implementation note.** `FakeProvider` and cassette record/replay are
> split into two components rather than the one this section describes: a
> cassette recorder is a decorator over a *real* provider (it wraps an
> adapter's HTTP transport), while `FakeProvider` is a leaf that never
> touches disk — one class cannot be both without a mode branch deciding
> which it is on a given call. Their keys differ too: `FakeProvider` hashes
> `(model, messages, response_schema, seed)` (the schema is added because
> two different schemas over the same prompt must not synthesise the same
> shape), while a cassette's match key is `sha256(method + scrubbed_url +
> canonical_body)` — the literal wire request, canonicalised so a JSON key
> reordering between SDK versions doesn't invalidate every recorded
> cassette, and scrubbed *before* hashing so a redacted cassette still
> replays. `sul.providers.cassette.CassetteTransport` implements the
> record/replay half; `sul.providers.fake.FakeProvider` implements the
> synthesis half. The budget kill switch (§M4) also lands here rather than
> in M4: `sul.providers.budget.BudgetGuard` is a pre-call gate in the shared
> call path (`sul.providers.client.ModelClient`), so every provider is
> covered from the moment providers exist, and M4's runner only has to
> supply the ceiling. `configs/pricing.yaml` carries dated Anthropic
> per-token prices (2026-06-24); OpenAI and Gemini sections are
> intentionally empty — this repo has no authoritative current rate card
> for either, and `sul.pricing.price_for` raises `UnknownModelError` for an
> unpriced `(provider, model)` rather than defaulting to `$0.00`. Finally,
> `sul cost <study_id>` (named by this section's own acceptance criterion)
> is implemented in `src/sul/cli.py` now, ahead of the rest of the Typer
> CLI, which remains M7's scope.

**Acceptance:** `make test` passes with no network (verify by running with network
disabled). Cost for a demo run is queryable via `sul cost <study_id>`.

---

### M3 — Persona system

- `configs/panel.example.yaml` defines archetypes and a target distribution:

```yaml
seed: 42
size: 40
segments:
  - name: time_poor_professional
    weight: 0.35
    attributes:
      tech_comfort: [high, medium]
      patience: low
      goals: ["evaluate quickly", "avoid setup work"]
      constraints: ["will not read docs", "on mobile"]
  - name: cost_sensitive_student
    weight: 0.4
    ...
```

- Sampler expands this into N personas with a seeded RNG, then renders each into
  a natural-language **persona card** used as the persona agent's system prompt.
- Cards must include a behavioural floor: personas are told to be a *user*, not a
  reviewer — to act, get confused, give up, and say so, rather than critique.
- Validation: realised segment proportions within tolerance of targets.

**Acceptance:** running the sampler twice with the same seed produces
byte-identical output. Changing only the seed changes the personas but not the
segment proportions beyond tolerance.

---

### M4 — Orchestrator (the core)

Async runner over the persona × scenario grid.

- Concurrency cap (config), exponential backoff with jitter on `RateLimited`.
- **Budget kill switch**: a study declares `max_cost_usd`; the runner refuses to
  start a call that would exceed it and exits cleanly with partial results saved.
- Resumability: interrupt mid-study, re-run, and it continues from the last
  completed run rather than starting over or duplicating.
- Turn loop: Moderator opens with the scenario task → Persona responds in
  character → Moderator asks up to *k* follow-ups (config, default 3), probing
  only on confusion or abandonment signals → Analyst runs after the transcript
  closes and emits `Finding[]` against a fixed taxonomy
  (`blocker`, `confusion`, `missing_info`, `trust`, `pricing`, `delight`).
- **Context isolation is enforced in code, not by prompt wording.** The persona
  agent's message list is constructed from persona card + artefact + moderator
  turns only. Add a test that asserts the research goal string never appears in
  any persona-bound payload.

> **M4 implementation note.** The budget kill switch described above already
> landed in M2 (`fc82b72`, see the M2 implementation note
> above): `sul.providers.budget.BudgetGuard` is a pre-call gate inside
> `ModelClient._dispatch`, checked before every dispatch regardless of
> milestone, with `test_budget.py` asserting the blocked call's provider is
> never invoked. This acceptance criterion is not unmet and does not need
> reimplementing here — M4's runner only needs to construct a `BudgetGuard`
> from the study's `max_cost_usd` and pass it to each `ModelClient` it
> creates.

**Acceptance:** 20 personas × 1 scenario against `artefacts/bad_onboarding.html`
completes offline via FakeProvider; all transcripts and findings persist; kill
the process at 50% and re-run — it completes without duplicate `Run` rows.

---

### M5 — Analysis and reporting

- Deduplicate and cluster findings across personas (TF-IDF + agglomerative
  clustering via scikit-learn is sufficient and keeps the dependency list short;
  embeddings are an upgrade, not a requirement).
- Rank clusters by `frequency × mean severity`, with per-segment breakdown so you
  can say *"blocks 8/14 cost-sensitive students, 1/12 professionals."*
- Render Markdown + HTML report: top findings, segment table, and for each
  cluster the verbatim supporting quotes with run IDs.

**Acceptance:** `sul report <study_id>` produces a report in which **every**
finding links to at least one transcript turn. Add a test that fails if any
rendered finding has zero evidence.

---

### M6 — Validity harness ⭐ *the milestone that makes this project worth talking about*

`make validate` runs five checks and writes `docs/validity_report.md`:

1. **Reproducibility** — same seed, same model, N repeats. Report variance in
   finding counts and in the top-5 cluster overlap (Jaccard). Non-zero variance is
   fine; unreported variance is not.
2. **Discriminative validity** — run the panel on `good_onboarding.html` and
   `bad_onboarding.html`. The bad artefact must produce materially more
   `blocker`/`confusion` findings. *If it doesn't, the tool is measuring nothing —
   report that honestly.*
3. **Acquiescence bias** — ask matched positively- and negatively-framed versions
   of the same question ("was the pricing clear?" / "was anything unclear about
   the pricing?"). Measure how often the panel simply agrees with the framing.
4. **Position bias** — where a scenario presents options, shuffle order across
   runs and measure preference shift attributable to position alone.
5. **Known-answer calibration** — at least three seeded ground-truth defects in
   the bad artefact (e.g. a required field with no label, a CTA that goes
   nowhere, a price that contradicts the pricing table). Report detection rate.

Write `docs/limitations.md` from the results: where the panel is useful, where
it is not, and what it systematically misses.

**Acceptance:** validity report generated end-to-end offline; `docs/limitations.md`
states at least two concrete, measured weaknesses.

---

### M7 — Interface and packaging

- Typer CLI: `sul personas sample`, `sul run`, `sul report`, `sul cost`,
  `sul validate`.
- FastAPI + Jinja/HTMX dashboard: study list → run list → transcript view →
  report view. Read-only is fine.
- Dockerfile + docker-compose. `make demo` runs a complete study with
  `FakeProvider` and no API key.

**Acceptance:** fresh clone → `docker compose up` → `make demo` → dashboard shows
a completed study with report, **without any API key set**. This matters: a
reviewer with no keys can still see it work in 60 seconds.

---

### M8 — Documentation

`README.md` with: one-paragraph what/why, architecture diagram, 60-second demo
instructions, a cost table (what a 40-persona study actually costs per provider),
the limitations section, and "what I'd do differently with real participants."

---

## 5. Guardrails — do not do these

- Do not use real user data, real transcripts, or any PII. Fixture artefacts only.
- Do not let persona agents see the research goal, each other, or prior findings.
- Do not write tests that call a real API.
- Do not claim in the README that this replaces user research.
- Do not add browser automation in v1. Scope creep here kills the project.
- Do not skip the FakeProvider to "move faster" — without it there is no test
  suite, and without a test suite this is a demo, not a project.

---

## 6. Interview questions to be able to answer

Build so these have real answers:

- How do you stop the personas from all sounding the same? *(Show the variance numbers.)*
- How do you know the panel isn't just telling you what you want to hear? *(M6.3.)*
- What does the tool systematically miss? *(M6, limitations.md.)*
- What happens when a provider rate-limits you halfway through a 40-persona study? *(M4 resumability.)*
- Why isolate the sub-agents' context? *(Because a persona that sees the hypothesis confirms the hypothesis.)*
- What did a study cost, and what drove the cost? *(ModelCall table.)*

---

## 7. CV bullets available on completion

Fill the brackets from real output — don't estimate.

- Built a multi-agent research harness that runs panels of [40] LLM-simulated
  users against product artefacts, with role-isolated moderator/persona/analyst
  agents to prevent hypothesis leakage into responses.
- Designed a provider-agnostic LLM layer with record/replay cassettes, per-call
  cost accounting and budget kill-switches; full test suite runs offline in [X]s
  with zero API spend.
- Built a validity harness measuring reproducibility, discriminative validity,
  acquiescence bias and known-defect detection rate ([X]%), and documented the
  conditions under which synthetic panels are and are not informative.
- Implemented resumable async orchestration with concurrency limits and
  exponential backoff, recovering [N]-run studies from mid-flight interruption
  without duplicate work.
