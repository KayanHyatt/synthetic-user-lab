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
> both remain out of scope for M1. A single `evidence_turn_id` per `Finding`
> (not a list, not a separate join table) is enough precisely because
> "many quotes, one theme" is represented by *many `Finding` rows sharing one
> `cluster_id`*, not by one `Finding` row holding many evidence turns —
> `cluster_id` is what makes the single-evidence-turn design non-lossy.
> **Amended in M5:** that grouping is computed at report-render time over the
> existing `Finding` rows (`sul.analysis.clustering`), not read off a stored
> `cluster_id` value — M5's own deviation note explains why the column stays
> `NULL`. The reasoning above still holds: nothing about it depended on
> `cluster_id` being *persisted*, only on grouping-by-theme existing as a
> concept applied over many single-evidence-turn `Finding` rows, which it
> still does. A reader landing on this note should not conclude clustering is
> persisted — see §M5.

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

> **M3 implementation note.** This section's example YAML uses a bare list
> for two different meanings — `tech_comfort: [high, medium]` reads as "pick
> one", `goals: ["evaluate quickly", "avoid setup work"]` reads as "hold
> both" — and a bare list cannot mean both. `configs/panel.example.yaml`
> instead requires an explicit wrapper on every attribute value: `choice:
> [...]` (pick one), `all: [...]` (hold all), `sample: {from: [...], k: N}`
> (pick N); a bare scalar (`patience: low`) is unambiguous and stays legal.
> **A bare list is a validation error, not a defaulted meaning** —
> `sul.personas.archetypes.AttributeSpec._coerce` rejects it, naming all
> three wrappers. The reasoning: a persona holding one goal instead of two is
> still a plausible persona, so nothing downstream would ever flag the
> mistake — it would only ever surface as unexplained noise in M6's validity
> numbers. Target proportions are declared in exactly one place,
> `SegmentSpec.weight`; the attribute wrappers are unweighted and
> `extra="forbid"` rejects a `weight` key on one, so there is no second place
> for a proportion to drift from the first. Segment *counts* are apportioned
> from those weights by the deterministic largest-remainder method
> (`sul.personas.sampler._apportion_counts`) rather than drawn at random, which
> is what makes "changes the personas but not the segment proportions"
> exact rather than merely within-tolerance. Every other random draw is keyed
> per `(panel seed, persona index, attribute key)`
> (`sul.personas.sampler._attribute_rng`), not pulled sequentially off one
> shared stream — inserting an unrelated attribute into the YAML cannot
> reshuffle any other attribute's realised value
> (`tests/test_persona_sampler.py::test_attribute_insertion_does_not_reshuffle_other_attributes`).
> `Panel.config_yaml` (`sul.personas.persistence.persist_panel`) stores a
> *resolved config snapshot* re-serialised from the validated `PanelConfig` —
> never the raw source YAML file — so a comment-borne or stray-key research
> goal cannot survive into the row even by accident; round-tripping
> sample→persist→rebuild-from-only-`Panel.seed`-and-`Panel.config_yaml` is
> itself an acceptance test (`tests/test_persona_persistence.py`), bought
> early against the same failure mode M6's reproducibility check exists to
> catch. `render_card` (`sul.personas.cards`) takes a `SampledPersona` and
> nothing else — no ORM object, no goal/topic/brief parameter — because
> `SampledPersona` cannot express a research goal or a sibling persona in the
> first place.

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

> **M4 isolation carry-forward (recorded during M3, unimplemented until this
> milestone).** M3 built the persona-card half of context isolation
> (`sul.personas.cards.render_card`, keyed only off `SampledPersona`) and
> deliberately left the rest for here, since M3 makes no LLM calls and builds
> no prompt sent to a provider. When M4 is implemented:
>
> - Every persona-bound prompt is built from `PersonaContext`
>   (`sul.schemas.isolation`) and nothing else — no ORM `Study`, `Panel`, or
>   sibling `Persona` crosses into a prompt builder, even read-only, even
>   "just for the id". If a builder needs a field `PersonaContext` doesn't
>   carry, that is a spec conversation, not a new keyword argument.
> - `lazy="raise"` on `Persona.panel`/`Panel.study` is a tripwire, not a
>   guarantee — it stops attribute traversal, not a fresh `session.query`, a
>   `selectinload`, or the goal arriving as a plain string named `topic` /
>   `brief` / `context` / `framing`. The string channel is the one to assume
>   leaks.
> - Add a test that captures the exact string(s) sent to the provider for a
>   persona turn and asserts the study goal text and every other persona's
>   name/attributes are absent, using sentinels distinctive enough to
>   substring-match (`ZZGOALZZ`, not `"usability"`) — test the rendered
>   prompt, not the object graph.
> - The moderator is a documented, deliberate goal-laundering channel: it
>   sees the goal and writes the questions personas answer, so the goal
>   reaches personas indirectly through those questions. That is the correct
>   design here — real moderators do exactly this — but the raw goal string
>   is never passed through verbatim.
> - Moderator adaptivity is the cross-persona leak: if one moderator instance
>   runs the whole panel and adapts follow-ups from what it has heard,
>   persona B is seeing persona A through the questions. Moderator state —
>   and any transcript/history list — is scoped **per persona session**, not
>   constructed once and shared or appended to across a loop over personas.
>   Test it: run two sessions where the first says something distinctive, and
>   assert that string never appears in the second's prompts.
> - Per-call seed derives deterministically from `(study seed, persona id,
>   turn index)` — never `uuid4`, wall-clock time, or dict/set iteration
>   order. If persona identity isn't in the seed and prompts are similar,
>   every persona answers identically under `FakeProvider`, the panel looks
>   like one person, and the isolation tests pass vacuously because there is
>   nothing distinctive left to leak.
> - Agents receive an injected `ModelClient`
>   (`sul.providers.client.ModelClient`) and never construct a provider
>   themselves — no agent takes `provider: Provider | None = None` and
>   defaults to a real one. One logical turn writes exactly one `ModelCall`
>   row (two if a repair turn fires); personas are never batched into a
>   single call to save tokens, since per-persona attribution is load-bearing
>   for M5 and M6.
> - Persona output is a Pydantic model parsed through M2's structured-output
>   path (one repair turn, no second repair layer, no fallback defaults, no
>   post-hoc string cleaning of a response).
> - Every quote an Analyst attributes to a persona (M4/M5) must be verified
>   against the stored transcript before it can land in a `Finding` — exact
>   substring or an explicit span reference, rejected loudly on mismatch.
>   Trusting the model's own quoting is the easiest thing in this project to
>   fake convincingly.
> - Prompt templates live in files, not string literals scattered through
>   agent code (M3 already does this for the persona card:
>   `sul/personas/templates/persona_card.v1.j2`, named by
>   `CARD_TEMPLATE_VERSION`); whatever identifies the template version is
>   recorded with the call.

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

> **M5 implementation note.** No LLM call anywhere in this milestone — no new
> `ModelClient`, no seed derivation, no `ModelCall` row, no budget
> interaction. `sul.analysis.clustering.cluster_findings` and
> `sul.analysis.ranking.rank_clusters` are pure, offline aggregation over
> `Finding`/`Turn` rows M4 already wrote; `sul.report.build.build_report`
> does the only database access in this milestone, and it is read-only (see
> below).
>
> **Clustering.** TF-IDF (`sklearn.feature_extraction.text.TfidfVectorizer`)
> + `AgglomerativeClustering(n_clusters=None, distance_threshold=..., metric
> ="cosine", linkage="average")` over `Finding.summary` text.
> `sul.analysis.config.ClusteringConfig` (`extra="forbid"`) holds
> `distance_threshold` (default `0.6`), `metric`, `linkage`, and the
> vectorizer's `stop_words`/`min_df` — a config model, not literals in the
> clustering module, per this project's own convention for tunables — with
> `configs/clustering.example.yaml` documenting the defaults and `sul report
> --clustering-config PATH` able to override them. The default threshold was
> chosen *from* `tests/test_clustering.py`'s discrimination fixture (built
> first), not picked and validated after: near-duplicate paraphrases must
> merge, distinct problems phrased in the same uniform "Analyst voice" must
> stay apart. Both directions pass at 0.6, but the margin is asymmetric, and
> `sul.analysis.clustering`'s module docstring documents why — TF-IDF cosine
> over Analyst-authored text partly measures the Analyst's phrasing
> uniformity, not just the panel's actual agreement. That is a property of
> the method, not a bug in this implementation, and is exactly the kind of
> thing M6's validity harness exists to measure.
>
> Degenerate inputs are handled explicitly (zero findings, one finding, an
> all-stop-word corpus, and — found only by the cross-process determinism
> test against `FakeProvider`'s synthesised summaries, not anticipated up
> front — a single summary short/generic enough to vectorise to an all-zero
> row even though the corpus as a whole has vocabulary, which `sklearn`'s
> cosine metric rejects outright). Cluster *numbering* is renumbered after
> fitting by the ascending `Finding.id` of each cluster's lowest-id member,
> read off each member's own attribute rather than its position in the input
> — `AgglomerativeClustering`'s raw labels are a function of input row order
> (verified by hand, not assumed), and an earlier version of the stability
> test used set-equality between a forward and a reversed call, which a
> small fixture satisfied *by coincidence* even with the renumbering step
> deliberately broken; the shipped test asserts the renumbering contract
> directly against a fixture where that coincidence doesn't occur.
>
> **Ranking.** `frequency × mean severity`. Frequency counts distinct
> personas contributing to a cluster, never raw `Finding` rows, so one
> persona with two findings in a cluster cannot manufacture the appearance
> of consensus. Mean severity is a mean *of per-persona means*, not a flat
> mean over findings, for the same reason — a flat mean would give that same
> persona double weight in the severity half of the formula while the
> frequency half normalises them to one unit, so the two halves would
> disagree about what a unit is. Rendered labelled "mean severity
> (model-assigned, 1-5; averaged per persona)" — it is the Analyst's
> assessment, not a measurement. Ties break on the lowest member `Finding.id`,
> never dict/set iteration order. Segment breakdown lists every segment
> present in the study for a cluster, including 0/N — omitting a
> zero-frequency segment would read as "not measured" rather than "measured,
> nobody in that segment reported it".
>
> **Category is not pre-partitioned.** Clustering runs globally across all
> findings regardless of `FindingCategory`; partitioning by category first
> would make theme structure depend on the Analyst's categorisation
> consistency and would prevent one underlying problem from clustering
> across two categories. Each cluster instead carries its modal category
> plus a `category_disagreement` flag when members disagree — a signal, not
> noise to suppress.
>
> **Deviation: `Finding.cluster_id` (declared in M1) is never written.**
> `sul report` computes clustering fresh on every invocation and never
> persists it. A persisted `cluster_id` would need its own
> config-provenance record to detect staleness against a re-cluster with
> different settings, or a flag gating re-clustering — either way, more
> machinery than this milestone's acceptance criterion needs, and either way
> `sul report` becomes a command that can silently rewrite a completed
> study's own rows, which is in tension with "never delete, merge or rewrite
> a `Finding` row." `tests/test_report_build.py
> ::test_cluster_id_is_never_written_to_the_database` and
> `tests/test_cli_report.py::test_sul_report_does_not_modify_the_database_file`
> (the latter hashing the whole database file before/after — a stronger
> check than inspecting one column) both guard this. See the amended M1 note
> above for why the original single-`evidence_turn_id` design doesn't depend
> on this column being persisted.
>
> **Persona identity comes from `Finding.run_id`, not from
> `evidence_turn_id -> Turn -> Run -> Persona`.** The two paths agree today
> only because M4 scopes the Analyst to one run at a time;
> `sul.report.build.build_report` reads `Finding.run_id` directly for
> persona/segment attribution and separately asserts the resolved evidence
> turn's own `run_id` matches, rather than assuming it.
>
> **Segments are reached by an explicit column join**
> (`Persona.segment`/`Panel.study_id`/`Persona.panel_id` are plain
> columns/FKs), never by walking `Persona.panel` or `Panel.study`, which
> stay `lazy="raise"` (unchanged from M1/M4).
>
> **Rendering.** One `sul.report.model.ReportModel` (`extra="forbid"`
> throughout), rendered to both formats by `sul.report.markdown` and
> `sul.report.html` — no field on it is ever populated from wall-clock time,
> hostname, cwd, an absolute path, or runtime introspection beyond the one
> deliberately-recorded `sklearn.__version__` string; there is no
> `generated_at` field. Cross-process byte-stability
> (`tests/test_report_determinism.py`) is checked via two separate `python`
> invocations of `tests/support/run_report_script.py` under different
> `PYTHONHASHSEED`, not by rendering an identical in-memory `ReportModel`
> twice in one process — a same-process check cannot catch a wall-clock- or
> iteration-order-shaped defect, since the value is already fixed by the
> time both renders happen. `Turn.content` is escaped per format: HTML uses
> Jinja `autoescape=True` (the one correct mechanism for HTML); Markdown has
> no single escaping mechanism, so every quote is wrapped in a fenced code
> block whose backtick-fence length is chosen longer than the longest
> backtick run already in the quote (`sul.report.markdown._fence`) — inside
> a fenced block CommonMark treats the content as literal, so `#`, `>`, `|`,
> backticks and embedded newlines never need per-character escaping.
> `Finding.summary` (the Analyst's paraphrase) is rendered as plain
> prose, separately labelled, and is never wrapped in a quote or attributed
> to a persona; it does not get the same fencing treatment as the verbatim
> quote, since it is expected to be short single-line prose rather than
> arbitrary model output — a residual risk if that assumption is ever wrong,
> noted rather than silently accepted. Long quotes are kept whole in both
> formats; HTML collapses them behind `<details>` past 400 characters,
> Markdown has no equivalent and keeps them inline — the report never
> excerpts a quote, since deciding what to cut is exactly the kind of
> judgement call this project keeps out of model hands.
>
> **A standing caveat** ("this panel is LLM-simulated, quotes are model
> output, not people") renders in both formats
> (`sul.report.model.SIMULATED_PANEL_CAVEAT`) — not named by this section's
> text, added because the report is the artefact most likely to be mistaken
> for real research, and the README/guardrail constraint against overclaiming
> applies to it specifically.
>
> **`sul report <study_id>`** (`src/sul/cli.py`) writes both formats to
> deterministic paths (`{out-dir}/study_{id}_report.{md,html}`, default
> `--out-dir reports/`), prints the resolved paths, and exits non-zero on an
> unknown study id. `--include-failed` includes `FAILED` (not just
> `COMPLETED`) runs; `PENDING`/`RUNNING` runs are always excluded (non-
> terminal). The report always states how many runs were excluded and in
> which status — never a silent denominator.
>
> **Dependencies.** `scikit-learn` added (`pyproject.toml`), with a
> `[[tool.mypy.overrides]]` entry scoped to `sklearn.*`
> (`ignore_missing_imports = true`, no type stubs shipped) — not a global
> mypy relaxation. `.\make.ps1 check` needed no other configuration change.
> `jinja2` was already a direct dependency (M2); `sul.report` is a new
> consumer of it, not a new dependency. `reports/` added to `.gitignore` as
> a generated-output directory, the same treatment as `*.db`.

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
