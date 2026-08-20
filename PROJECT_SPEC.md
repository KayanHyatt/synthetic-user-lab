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

> **M2 cross-reference (added in a later session, landed as part of §M6's
> Deviation 10).** `AnthropicProvider.complete` no longer merely accepts and
> ignores `response_schema` — it turns it into a native `output_config
> .format` JSON-schema constraint on the request. This reverses that
> class's own docstring claim, unchanged since this milestone, that the
> schema is "not enforced API-side... so every adapter behaves identically
> regardless of whether the underlying API has a native structured-output
> mode." A reader relying on that sentence should follow this pointer to
> §M6's Deviation 10 rather than assume it still describes the code. The
> repair-turn mechanism this section itself specifies is untouched — it
> still fires exactly once, still on any provider, still without regex or a
> fallback default; only the Anthropic adapter changed, and only in how it
> builds the outgoing request.

> **M2 environment note.** The first real (non-cassette) call to the
> Anthropic API from this Windows machine, via `AnthropicProvider`, worked on
> the first try with `SSL_CERT_FILE` set to a Windows root-store export
> (`windows-roots.pem`) — no `httpx`/`certifi` cert-bundle wrangling needed.
> Recorded so a future session doesn't re-diagnose TLS before assuming a code
> problem.

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

> **M4 deviation (post-milestone): per-agent model override.** `run_study`
> gained an optional `model_by_agent: dict[AgentRole, str] | None = None`
> keyword, resolved independently at each of the three dispatch sites inside
> `_run_one_persona` (persona turn, moderator follow-up, analyst) against a
> fallback to the existing single `model` argument — an agent absent from
> the mapping (including every agent, when the argument is omitted entirely)
> dispatches on `model`, unchanged from before this existed. This is not
> something the spec's turn loop called for; it exists to let a study run
> the Persona and Moderator on one model while the Analyst runs on another,
> for the two-configuration recording pass (config B = config A with the
> Analyst swapped) that follows this milestone. `ModelClient`/`ModelCall`
> needed no change — the `model` string was always a per-dispatch argument,
> never fixed at `ModelClient` construction, so each agent's `ModelCall` rows
> already record whichever model actually served that call. Covered by
> `tests/test_model_by_agent.py` (routing, backward-compatible omission,
> and partial-mapping fallback for unlisted agents); `configs/pricing.yaml`
> gained four zero-cost `fake:` entries so those tests can assert distinct
> `ModelCall.model` values per agent without three dispatches colliding on
> the pre-existing `fake-1`.

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
>
> **Deviation 5 (recorded in M6, landed in M5).** `pyproject.toml` also
> gained a `[tool.ruff.lint.flake8-bugbear]` relaxation in this milestone's
> commit, for `sul report`'s Typer options:
> ```toml
> [tool.ruff.lint.flake8-bugbear]
> extend-immutable-calls = ["typer.Argument", "typer.Option"]
> ```
> `typer.Option(...)`/`typer.Argument(...)` as a signature default is the
> documented Typer pattern, not the mutable-default footgun B008 exists to
> catch — the calls are immutable, constructed once at import time. This was
> omitted from this section's deviation list when M5 actually shipped it;
> recorded here because a lint relaxation belongs where relaxations are
> recorded, not only in the `pyproject.toml` inline comment next to it.

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

> **M6 implementation note.** This section's own header names criterion 5
> "Known-answer calibration"; its body specifies recall against a fixed
> known-answer set ("Report detection rate"), not a confidence score. The
> two names don't describe the same statistic — `sul.validity.calibration`
> implements the body (detection rate), and this note exists so a future
> reader doesn't reopen the question the header seems to ask.
>
> **Deviation 1: `sul validate` added to `src/sul/cli.py` in this milestone**,
> ahead of `personas sample`/`run`, following the precedent §M2 set for `sul
> cost` and §M5 set for `sul report` — both landed early "ahead of the rest
> of the Typer CLI," which is exactly this situation. `.\make.ps1 validate`
> now runs `uv run sul validate`.
>
> **Deviation 2: `artefacts/good_onboarding.html` authored.** Named by §3's
> repo layout and anticipated by `bad_onboarding.html`'s own M4 fixture
> comment, but never created through M1–M5. Same product, same structure,
> same length as the bad artefact, with its three seeded defects fixed —
> built for a fair discriminative-validity comparison, not a differently
> shaped page.
>
> **Deviation 3: two new probe types, outside the M4 turn loop.** Nothing in
> M4's turn loop can pose a specific, experimenter-chosen question and get a
> directly comparable structured answer back — the moderator's follow-up is
> LLM-chosen and gated on a confusion/abandonment signal, and
> `PersonaReply.utterance` is free text with no agree/disagree or
> choice-among-options field. §M6.3/§M6.4 need exactly that, so
> `sul.validity.probes` adds `run_framing_probe`/`run_choice_probe`: one
> isolated call each (persona card + artefact + one fixed prompt, no
> transcript, no research goal), built the same way `sul.agents.persona`/
> `moderator`/`analyst` are (`ModelClient` injected, one `.v1.j2` template
> per probe, `template_version` recorded with the call —
> `framing_probe.v1`/`choice_probe.v1`). `sul.validity.schemas
> .FramingProbeContext`/`ChoiceProbeContext` are the isolation boundary
> (`extra="forbid"`, no research-goal field to accept one in the first
> place), same discipline as `sul.schemas.isolation.PersonaContext`. Neither
> probe reuses `PersonaReply`: acquiescence/position-bias need a structured
> answer a metric can compare directly, not free text a metric would have to
> string-match — the same "never regex an LLM response" reasoning that
> already governs `sul.schemas.agents`. `AgentRole.VALIDITY_PROBE` was added
> (`sul.enums`) so these calls' cost is distinguishable from ordinary M4
> turn-loop spend in a `sul cost` breakdown, the same reasoning `AgentRole
> .ANALYST` was added for in M1: a `ModelCall` with a `run_id` but no `Turn`.
>
> **Deviation 4 (the load-bearing one): §M6.2–§M6.5 report an explicit
> `NOT_MEASURED_OFFLINE` state under `FakeProvider`, never a number.**
> `FakeProvider` draws `AnalystFinding.category` uniformly at random and
> `AnalystFinding.summary`/probe replies as hash-keyed noise, blind to
> artefact content, question framing, and option position alike — any number
> these four checks produced against `FakeProvider` would be sampling noise
> wearing the shape of a result. `sul.validity.sentinel.MeasurementStatus` is
> a distinct enum value (never an absent/`None`/zero field) rendered visibly
> in both `sul validate`'s output and `docs/validity_report.md`, with a
> one-line reason. Every metric module still *runs* end to end against
> whichever provider it's given — there is no FakeProvider-specific branch
> inside `sul.validity.discriminative`/`.acquiescence`/`.position`/
> `.calibration`; `sul.validity.harness._is_offline_provider` is the one,
> central place that decides whether a computed result is worth showing a
> reader, based on `provider_name` alone (`"fake"` gates; any other name,
> including a cassette-backed real adapter, does not). This is why
> `docs/validity_report.md` and `docs/limitations.md` are still "generated
> end-to-end offline" per this section's own acceptance line: the pipeline
> runs; only the reported numbers are gated.
>
> Reproducibility (§M6.1) is not gated — it is the one check that's
> genuinely meaningful under `FakeProvider`, because the entire pipeline
> (`derive_seed` → a pure sha256-keyed synthesis → clustering's
> `Finding.id`-ordered tie-breaks) is deterministic by construction. Its
> number is real but not rich: same-seed repeats show exactly zero variance
> and exactly 1.0 top-5 cluster Jaccard overlap every time, and
> `sul.validity.model.REPRODUCIBILITY_CAVEAT` — rendered directly beside the
> numbers, not as a separate footnote — says so explicitly: this measures
> the harness's own determinism, not the panel's. `sul.validity
> .reproducibility` also measures seed sensitivity (different seeds, not the
> same one) as an addition beyond §M6.1's own text: unlike same-seed
> reproducibility, `FakeProvider`'s hash includes the seed, so this is
> genuinely offline-meaningful — it measures how much the clustering/ranking
> pipeline amplifies input variation, not panel realism.
>
> **Deviation 4a: reproducibility always runs against `FakeProvider`,
> unconditionally, never against whatever provider backs the other four
> checks.** `CassetteTransport` matches on `method + scrubbed_url +
> canonical_body` and replays exactly one recorded response per key.
> Same-seed, N-repeat reproducibility sends N *identical* requests (`seed`
> itself is never part of the wire body, so it can't disambiguate them even
> if it mattered) — recording collapses to one surviving response (each
> repeat's write overwrites the last) and replay returns that one response N
> times. A cassette cannot carry real same-seed-repeat variance even in
> principle; this is a structural property of one-key-one-response replay,
> not a gap specific to `FakeProvider`. Extending `CassetteTransport` to
> support multiple responses per key with ordinal replay was considered and
> declined for this milestone (an M2 change, needing its own cross-process
> determinism test and explicit sign-off not given in advance).
> `sul.validity.harness.run_validity_harness` therefore constructs its own
> `FakeProvider()` for `measure_reproducibility` regardless of the `provider`
> it was itself given — proven by `tests/test_validity_harness
> ::test_reproducibility_never_touches_the_harness_level_provider`, which
> passes a provider that raises on any call and confirms reproducibility
> still completes. `REPRODUCIBILITY_CAVEAT` (`sul.validity.model`) says this
> explicitly: this check never runs against a real or cassette-backed
> provider, permanently, not just today.
>
> **Deviation 5: cassette-backed replay is supported as a first-class
> parameter, and `sul validate` now constructs one automatically whenever
> committed cassettes exist to replay.** Every §M6.2–§M6.5 function takes
> its `LLMProvider` as a parameter — `FakeProvider` and a cassette-backed
> `AnthropicProvider` are just two callers of the same code.
> `tests/test_validity_cassette_plumbing.py` proves the full path (
> `ModelClient` → `AnthropicProvider` → `CassetteTransport` replay → parsed
> Pydantic reply) works, against a cassette hand-authored via
> `httpx.MockTransport` (the same no-network recording technique
> `tests/test_cassettes.py` already uses for the cassette layer itself) —
> never a live call.
>
> **Originally, `sul validate` hardcoded `FakeProvider` unconditionally.**
> At the time this milestone shipped, `tests/cassettes/` held nothing —
> recording a *real* cassette (spending real money, the first live call in
> this repo's history) was a separate, explicitly-authorised action outside
> this milestone's own scope, gated behind a decision the person running
> this project made with a cost estimate in hand, and there was nothing yet
> for `sul validate` to replay even if it had tried. Hardcoding
> `FakeProvider` was the correct call under that constraint: a flag that
> *could* point at a real provider but had nothing to replay would either
> hard-fail confusingly or (worse) silently fall through to a live call,
> and neither was acceptable in a milestone whose own acceptance line reads
> "validity report generated end-to-end offline."
>
> **That constraint is gone.** 46 real cassettes are now committed in
> `tests/cassettes/` (PROJECT_SPEC.md §M6 Deviation 12/13, Config A —
> Persona/Moderator/probes on `claude-haiku-4-5`, Analyst on
> `claude-sonnet-5`), and with them, hardcoding `FakeProvider` stopped being
> a safety measure and became a correctness bug: `docs/limitations.md`
> could describe real, measured numbers that `tests/cassettes/` genuinely
> backed, while `docs/validity_report.md` — the file `sul validate` itself
> writes, the one a reader actually opens — kept reporting `NOT MEASURED
> OFFLINE` for the same four checks, because the command generating it
> never looked at what was sitting beside it in the repo. `make validate`
> could no longer regenerate what the repo claimed to have measured; the
> constraint this deviation originally existed to protect had inverted into
> the thing breaking §M6's own acceptance criterion.
>
> `sul.cli._select_validate_provider` now makes the choice
> `run_validity_harness`'s own two-member allow-list already permits (§M6
> Deviation 7, unchanged): a cassette-backed, replay-only (`record=False`)
> `AnthropicProvider` when `settings.cassette_dir` holds at least one
> `*.json` file, else `FakeProvider` — still fully automatic, still no flag
> on the command (`tests/test_cli_validate.py` still checks this
> structurally against `--help`, now alongside a test that the *no-cassette*
> fallback path still gates correctly, forced via `SUL_CASSETTE_DIR`
> pointed at an empty directory, independent of whatever `tests/cassettes/`
> happens to hold at test-run time). The cassette-backed branch dispatches
> on the exact model configuration `tests/cassettes/` was recorded with
> (`_CASSETTE_CONFIG_MODEL`/`_CASSETTE_CONFIG_ANALYST_MODEL` in
> `sul/cli.py`) — any drift from that raises `CassetteMissError`, a hard,
> visible failure, never a silent live dispatch; "offline" has always meant
> "no live API call," not "always `FakeProvider`," and that distinction is
> what makes this deviation's change safe rather than a reopening of the
> constraint it describes. `docs/validity_report.md` is regenerated and
> committed under this behaviour now (`tests/test_validity_cassette_report
> _determinism.py` proves it reproduces byte-for-byte from the committed
> cassettes, cross-process, the same pattern `tests/test_report
> _determinism.py` established for `sul.report`); `docs/limitations.md`'s
> template gained a matching data-driven section (gated on
> `report.provider_name != "fake"`, not a static assumption that the report
> is always `FakeProvider`-backed) carrying the same model-tier caveat a
> prior version of this note put in a since-deleted separate file.
>
> **Deviation 7: `tests.support.scripted_provider.ScriptedProvider` is a
> second offline provider, alongside M2's `FakeProvider`, and it is
> deliberately more dangerous.** `FakeProvider` synthesizes from a hash,
> content-blind by construction — a wiring mistake that let it reach `sul
> validate` would still be caught by "the numbers don't move with the
> input." `ScriptedProvider` answers a script written against the actual
> prompt text; a mistake that let *that* reach `run_validity_harness` would
> produce numbers that respond sensibly to artefact/framing/position and
> would pass exactly the sanity checks a reviewer would apply — measuring a
> script instead of a panel, with no cassette and no live call, and no
> obvious tell. It exists only as a negative-control test double (every use
> in this milestone is inside `tests/`) and must never be permitted to back
> `sul validate`. `run_validity_harness` enforces this itself, structurally:
> `provider` is checked against an explicit two-member allow-list
> (`FakeProvider`, `AnthropicProvider`) before any dispatch, raising
> `UnsupportedValidityProviderError` — not a negation ("anything that isn't
> `FakeProvider`"), which would have let `ScriptedProvider` straight through
> the moment a recording script existed.
> `tests/test_validity_harness.py::test_scripted_provider_is_refused_at_the_harness_boundary`
> asserts the rejection by type.
>
> **Deviation 8: provenance (provider, and model per agent role) is a
> rendered field on every content-dependent section, read back from the
> `ModelCall` audit trail, not a single blanket value for the whole
> report.** Once real recording exists, one `validity_report.md` can carry
> some sections backed by `FakeProvider` and others by a cassette-backed
> real model — potentially a *different* model per agent role within one
> section (§M6.2's Analyst vs. its Persona/Moderator calls). A single
> top-of-report "Provider: X / model: Y" line (the original design) would
> have let a reader mistake a mixed run for one uniform experiment — the
> same failure this milestone exists to prevent, reached through the
> rendering layer instead of the measurement layer. `sul.validity.data
> .load_provenance` queries the real `ModelCall` rows for exactly the
> studies that produced a section's numbers (never a separately-threaded
> "what I asked for" value, which could drift from what actually got
> dispatched via a retry or backoff path) and returns one `AgentProvenance`
> per distinct `(agent, provider, model)` triple. `sul.validity.runs
> .run_artefact_study` now returns the materialised study id alongside its
> `Finding` rows (`ArtefactStudyRun`) so callers have something to query
> provenance against; `DiscriminativeValidityResult`, `AcquiescenceResult`
> and `PositionBiasResult` all carry their own `study_id`/`provenance`.
> `sul.validity.harness` attaches provenance to a section in both branches
> (`MEASURED` and `NOT_MEASURED_OFFLINE`) — what was actually dispatched is
> meaningful even when the resulting number is gated. `validity_report.md
> .j2` renders it twice: a `Provenance` column in a new top-of-report
> summary table (one row per check), and a `**Provenance:**` line inside
> each detailed section — never folded into the reason/caveat prose, which
> is exactly the "prose in a caveat" framing this deviation exists to avoid.
> `tests/test_validity_rendering.py
> ::test_provenance_is_rendered_per_row_not_collapsed_to_one_value`
> constructs a `ValidityReportModel` by hand with two sections carrying
> deliberately different provenance and asserts both survive into the
> rendered text distinctly.
>
> **Three offline-measurable additions to `docs/limitations.md`**
> (`sul.validity.measurements`), none gated, because none depend on an LLM:
> clustering margin (extends `tests/test_clustering.py`'s discrimination
> fixture with the actual cosine-distance numbers), zero-vector singleton
> conflation (a finding that vectorises to an all-zero TF-IDF row is
> indistinguishable, in a rendered report, from a genuine frequency-1
> theme), and threshold-scaling behaviour (`distance_threshold=0.6`'s
> cluster count / mean cluster size as corpus size grows, against
> deterministically-generated synthetic text — never against `FakeProvider`
> output, and the default is never changed: `ClusteringConfig` and
> `sklearn.__version__` are embedded in every `ReportModel`'s provenance,
> and changing the default would break comparability with every report
> already produced). `docs/limitations.md` states all three are measured
> weaknesses of the panel's analysis pipeline; the four gated §M6.2–§M6.5
> checks are named in a separate section and explicitly not counted toward
> them, since "we couldn't reach a real provider" is a limitation of running
> the harness offline, not a measured property of the synthetic panel.
>
> **Deviation 6: `docs/validity_report.md` and `docs/limitations.md` are
> committed generated files.** M5 gitignored `reports/` as ad hoc,
> per-study output; these two are not that — §M6 names them as the
> milestone's deliverables ("`make validate` runs five checks and writes
> `docs/validity_report.md`"; "docs/limitations.md states at least two
> concrete, measured weaknesses"), the same footing as the already-committed
> `docs/architecture.md`, not a run artefact a reviewer is expected to
> regenerate before reading. The cost of this reading: `make validate`
> dirties the working tree on every run (a fresh `sul.db`'s FakeProvider
> content is deterministic byte-for-byte, so re-running produces the same
> two files unless the harness itself changed — but git still sees them as
> modified until diffed). Regenerated and committed as part of this
> milestone's own commit whenever `sul.validity`'s output changes.
>
> **Deviation 9: a real recording pass (post-milestone) found real Haiku's
> structured output too unreliable to record a usable §M6.2 run.**
> `scripts/record_validity_cassettes.py` ran the panel_validity.yaml 5-persona
> panel against the real Anthropic API in two configurations (Persona/
> Moderator/probes on Haiku throughout; Analyst on Sonnet in config A, Haiku
> in config B) to record `tests/cassettes/` for the first time. §M6.2's
> discriminative-validity study failed **10/10** Runs (5 personas × bad +
> good artefact): real `claude-haiku-4-5` wraps its `PersonaReply` JSON in
> ` ```json ` code fences and invents field names (`narration`, `dialogue`,
> `persona_speech`, `narrative`, `message`) instead of the schema's
> `utterance`/`state`. M2's one bounded repair turn (`_REPAIR_INSTRUCTION`:
> "reply again with ONLY output that validates against the schema") did not
> recover a single one of the 10 — the second attempt repeated the same
> failure mode. Because the Analyst only dispatches after a persona turn
> parses successfully, **zero real Analyst calls were ever made in either
> configuration** — the comparison this recording pass exists to set up
> never got real data to compare. §M6.3's `FramingProbeReply` (a single
> `agreement` field) failed the same way on the acquiescence probe — a real
> reply added an unrequested `rationale` field and the repair turn didn't
> strip it either — but with a second consequence: `run_acquiescence_probe`
> has no per-subject error containment analogous to `_run_one_persona`'s
> `except (BudgetExceeded, StructuredOutputError)` (§M4's per-run boundary,
> this file's own M4 section), so the second failure propagated an uncaught
> `StructuredOutputError` and crashed the harness run outright, rather than
> marking one subject's probe failed and continuing. The 26 cassettes this
> pass recorded (real spend: $0.0578, `claude-haiku-4-5` only — the Sonnet
> Analyst was never reached) were deleted rather than committed: scrubbing
> was verified clean against them (`tests/test_real_cassette_scrubbing.py`,
> which now runs vacuously against the empty directory left behind), but
> their *content* is a failed experiment, not a usable recording. Fixing
> real-model structured-output reliability (stronger fence-stripping, a
> harder repair prompt, or moving to Anthropic's native tool-use/schema
> enforcement instead of prompted-JSON-plus-repair) is unstarted and
> deliberately not decided here — this note records the failure mode for
> whoever picks it up next, not a fix.
>
> **Amended in a later session (see Deviation 10).** The paragraph above
> reads as "real Haiku ignores the schema it was given." It doesn't — it was
> never given one, in any form. `src/sul/agents/templates/persona_system.v1
> .j2`, `moderator_followup.v1.j2`, and `analyst.v1.j2` (the three M4 turn-
> loop templates) contain **zero** output-format instructions; they describe
> the task in prose. `AnthropicProvider.complete` (pre-Deviation-10) bound
> `response_schema` as a parameter and never referenced it again in the
> function body — the adapter's own docstring said as much. So attempt 1 of
> every real call in this recording pass had no reason to emit JSON at all,
> and the one repair turn (`_REPAIR_INSTRUCTION`, quoted above) is the
> *first* format instruction the model ever saw — and even that shows it
> only pydantic's stringified `ValidationError`, never the JSON Schema
> itself. A 10/10 failure under those conditions is the expected outcome of
> the setup, not evidence that real Haiku's structured-output following is
> unreliable in general. This amendment does not retract the second
> consequence recorded above (`run_acquiescence_probe` had no per-subject
> containment) — that finding was independently correct and is fixed by
> Deviation 11 below. A reader landing on the original paragraph should not
> conclude real Haiku's structured output needed a workaround before it was
> ever actually asked for structured output.
>
> **Dependencies.** None. Variance/Jaccard use stdlib `statistics`/set
> arithmetic; `numpy` was already reachable (via `scikit-learn`, already
> imported directly in `sul.analysis.clustering`).
>
> **Deviation 10 (later session): `AnthropicProvider` now turns
> `response_schema` into a native `output_config.format` JSON-schema
> constraint, rather than accepting and ignoring it.** `sul.providers
> .anthropic.AnthropicProvider.complete` passes
> `output_config={"format": {"type": "json_schema", "schema":
> transform_schema(response_schema)}}` when a schema is given —
> `anthropic.transform_schema` (public SDK helper) relocates JSON Schema
> keywords `output_config.format` rejects outright (`minLength`,
> `minimum`/`maximum`, etc. — every `Field(ge=..., le=...)`/`Field
> (min_length=...)` constraint this project's schemas already use) into
> field descriptions rather than sending them raw, and pydantic still
> enforces them client-side afterwards regardless. This is a change to one
> file, not a Protocol change: `LLMProvider.complete` (§M2) already carries
> `response_schema: type[BaseModel] | None`, `Completion` stays text-only,
> and `sul.providers.client.ModelClient`'s one bounded repair turn is
> untouched — it stays live for `max_tokens` truncation and for the
> `sul.providers.openai`/`.gemini` adapters, which still ignore
> `response_schema` exactly as this adapter used to. **Reverses this
> class's own pre-existing docstring claim** ("not enforced API-side... so
> every adapter behaves identically") — see the cross-reference added to
> §M2's implementation note. Forced tool use (`tools` + `tool_choice` +
> `strict: true`) was considered and declined: the payload would arrive as
> a `tool_use` block's `.input` dict, requiring `Completion` to gain a
> structured field and `ModelClient`'s two `model_validate_json` call sites
> to branch on `model_validate` instead, plus `tools`/`tool_choice` threaded
> through the Protocol, both `ModelClient.complete` overloads, `_dispatch`,
> every adapter, and roughly fifteen test doubles — an M2-scale change
> `output_config.format` buys the same guarantee without.
>
> A second, independent 400 risk this recording pass never reached (zero
> real Analyst calls were ever made — see above): `AnthropicProvider` sent
> `temperature` unconditionally, and sampling parameters
> (`temperature`/`top_p`/`top_k`) are **removed** on Claude 4.6-and-later
> model families — `claude-opus-5`, `claude-sonnet-5`, `claude-opus-4-7`,
> `claude-opus-4-8`, `claude-fable-5`, `claude-mythos-5` among them. Config
> A's Sonnet Analyst would have hit this the moment a persona turn parsed
> successfully. `_accepts_temperature` (`sul.providers.anthropic`) omits
> `temperature` from the request for those model-name prefixes;
> `claude-haiku-4-5` is unaffected and still receives it, which is why
> nothing else in this recording pass 400'd. `tests
> /test_anthropic_structured_output.py` proves both changes offline, driven
> entirely through `httpx.MockTransport` (the same no-network technique
> `tests/test_cassettes.py` uses) — never a live call: `output_config`
> present with `type: json_schema` and no unsupported keyword surviving
> anywhere in the schema tree (checked recursively, since a nested `$defs`
> entry is exactly where pydantic places a non-root `Field` constraint) for
> every real schema in this codebase, `additionalProperties: false` on every
> object node, the per-run `Literal[valid_evidence_ordinals]` analyst schema
> arriving as a JSON Schema `enum`, `output_config` absent when no schema is
> given, and `temperature` present for Haiku / absent for Sonnet and Opus.
>
> **Deviation 11 (later session): the probe path gained per-subject
> containment, backoff, a per-section budget ceiling, and a third
> `MeasurementStatus` — the fix for this note's second consequence.**
> `sul.validity.acquiescence.run_acquiescence_probe` and `sul.validity
> .position.run_position_bias_probe` now wrap each subject's calls in
> `try/except (ProviderError, StructuredOutputError)`, scoped to the *whole*
> subject rather than one call: each subject feeds two sinks (positive/
> negative framing; original/reversed ordering), and `agreement_gap`/
> `preference_shift` are only meaningful as a paired comparison across them,
> so a subject that fails partway through is discarded from *both* sinks
> atomically — accumulated into a local list first, only extended onto the
> shared sinks once every call for that subject has succeeded. Each
> individual probe call is additionally wrapped in `call_with_backoff`
> (`sul.runner.retry`, already used by §M4's turn loop), and an optional
> `max_cost_usd` constructs a `BudgetGuard` scoped to that check's own
> materialised study — **per-check, not a shared whole-harness ceiling**:
> `run_validity_harness` gained the same parameter, forwarded unchanged to
> discriminative validity (which spends it twice, once per artefact study,
> via `run_artefact_study`, which now also accepts and threads it into
> `run_study`'s existing `budget` parameter), acquiescence, and position
> bias independently.
>
> A second bug, found while building this: `sul.validity.runs
> .materialize_probe_subjects` created every probe's `Run` row with
> `status=COMPLETED` and both `started_at`/`finished_at` set **before any
> probe call was dispatched** — every subject read `COMPLETED, error=None`
> regardless of whether its probe ever ran, the opposite of what §M4's own
> `_prepare_run` does for a turn-loop run. Probe `Run` rows now start
> `PENDING` and are resolved by new `mark_probe_run_completed`/
> `mark_probe_run_failed` helpers (mirroring, not importing,
> `sul.runner.orchestrator`'s private equivalents — a probe run has no
> `Turn`/`Finding` rows to reconcile).
>
> **`MeasurementStatus.PARTIALLY_MEASURED`** (`sul.validity.sentinel`) is a
> third enum member, not a count field bolted onto `MEASURED` — same
> reasoning `NOT_MEASURED_OFFLINE` was originally added for: a rate computed
> only over survivors, rendered identically to a full-panel rate, hides that
> the denominator shrank. `AcquiescenceSection`/`PositionBiasSection` gained
> `subjects_attempted`/`subjects_measured`, rendered next to every rate in
> `validity_report.md.j2` (`sul.validity.harness._probe_status` resolves the
> three-way status from those two counts alone). **Zero survivors
> (`subjects_measured == 0`) resolves to `PARTIALLY_MEASURED`, deliberately
> not `NOT_MEASURED_OFFLINE`** — that member's rendered label and reason
> text are specifically about `FakeProvider`'s content-blind synthesis and
> would misdescribe a real-provider section that dispatched real calls and
> simply lost every subject; every rate field is `None` in this case, never
> the `0.0` `agreement_rate([])`/`first_option_share([], ...)` would
> otherwise return, so a wiped-out section can never be mistaken for a
> confidently-measured, unbiased panel.
>
> **Section-level containment was added to `run_validity_harness` itself**
> for discriminative validity (+ the calibration measurement derived from
> it), acquiescence, and position bias — each wrapped in
> `except (ProviderError, StructuredOutputError)`, degrading to
> `PARTIALLY_MEASURED` with the exception as its reason while every other
> section, and every already-billed `ModelCall` behind it, survives into the
> returned report (§M4's "exits cleanly with partial results saved"
> contract, applied one level up). **Reproducibility (§M6.1) is deliberately
> excluded**: `ReproducibilitySection` has no `status` field at all — "always
> `measured`" is baked into its own docstring — so there is no value this
> containment could assign it without a model change outside this
> deviation's scope, and it is always dispatched against a freshly
> constructed `FakeProvider()`, never the harness-level `provider`, so a
> real provider's failure cannot reach it regardless.
>
> Not done, and out of scope for this deviation: `sul.runner.orchestrator
> ._run_one_persona`'s own per-run containment still only catches
> `(BudgetExceeded, StructuredOutputError)`, not `RateLimited`-exhausted /
> `Refused` / `BadRequest` / `Overloaded` — an M4-level gap this session
> found but did not fix, mitigated at the harness boundary above (which
> catches the broader `ProviderError` family) but not at its source.
>
> Tested offline throughout: `tests/test_validity_probe_containment.py`
> drives `run_acquiescence_probe`/`run_position_bias_probe` directly against
> `ScriptedProvider` (content-aware, and for exactly that reason refused at
> `run_validity_harness`'s own allow-list boundary — Deviation 7 — so it
> cannot exercise the harness-level status resolution) with a scripted
> failure on one subject, asserting the failed subject's `Run` row is
> `FAILED` with a non-null `error`, the surviving subjects' rows are
> `COMPLETED`, and both sinks land on the same rate as if the failed subject
> had never existed. Harness-level status resolution, zero-survivor
> gating, and section-level degradation are each proven separately by
> monkeypatching one probe function at a time (mirroring `tests
> /test_validity_harness.py
> ::test_reproducibility_never_touches_the_harness_level_provider`'s own
> pattern), since `ScriptedProvider` cannot reach `run_validity_harness`
> and `FakeProvider` never raises `ProviderError`/`StructuredOutputError` in
> the first place.
>
> No real cassettes were recorded or committed in this session, and no live
> API call was made — this deviation is the offline groundwork the next
> recording attempt needs; running `scripts/record_validity_cassettes.py`
> again remains a separate, explicitly-authorised action outside this
> session's scope.
>
> **Amended in a later session (see Deviation 12): the recording attempt
> happened, and it worked for Config A.** 46 cassettes are committed in
> `tests/cassettes/` — a complete, `MEASURED` Config A run. Config B never
> completed; §M6.5's calibration is Config A's Sonnet-Analyst numbers only.
> `tests/test_real_cassette_scrubbing.py` now runs for real against them
> (no longer vacuous) and passes.
>
> **Deviation 12 (later session): Config A recorded successfully ($0.1126
> real, 46 calls); Config B blocked by a cassette-replay bug, not a
> connection problem — corrected diagnosis, not fixed tonight.**
> `scripts/record_validity_cassettes.py` ran for real. Config A (Persona/
> Moderator/probes on `claude-haiku-4-5`, Analyst on `claude-sonnet-5`)
> completed in full — all four gated §M6.2–.5 checks came back `MEASURED`,
> 46 real calls recorded (ground truth summed from each cassette's own
> `usage` field: 36 Haiku, $0.0606; 10 Sonnet, $0.0519; total $0.1126). A
> real Sonnet Analyst cassette was inspected by hand: clean
> `{"findings":[...]}`, no fences, exactly the schema — Deviation 10 holds
> on the real Analyst path, not just the earlier single-call smoke test.
> All 46 cassettes were verified complete and parseable (valid JSON, 200
> status, non-empty text content, `stop_reason` never `max_tokens`) before
> anything was committed; none needed deletion.
>
> Config B (Analyst also on Haiku) never completed. The first live attempt
> got partway through Config B before failing; two subsequent verification
> re-runs (against a fresh, unconfounded database — the recording script's
> default `--db-path` is a fixed temp-dir filename that had stale rows from
> an earlier session, which is what made the first cost readout wrong and
> had to be redone) failed **immediately, on Config A too**, every dispatch,
> reported as `anthropic.APIConnectionError` ("Connection error."), $0
> billed each time.
>
> **First diagnosis offered for this (orphaned `asyncio` tasks racing a
> concurrent-request limit) was wrong, and was corrected before anything was
> committed.** The actual mechanism, confirmed fully offline with zero
> further live spend
> (`tests/test_real_cassette_scrubbing.py`-adjacent manual diagnostic, not
> committed — a hand-built `httpx.Request` reconstructed from each cassette's
> own recorded fields, replayed through `CassetteTransport(record_if_missing
> =True)` with a poison-pill inner transport that raises if ever touched):
> **every one of the 46 cassettes fails identically on replay** with
> `zlib.error: Error -3 while decompressing data: incorrect header check` —
> not a connection error at all. Real Anthropic responses arrive
> gzip-compressed (`content-encoding: gzip` in the recorded response
> headers — `tests/cassettes/*.json` shows this directly). `CassetteCore
> ._write` (`sul/providers/cassette.py`) stores `response.text` — httpx's
> already-decompressed body — as the cassette's `body`, but stores the
> *original* response headers, `content-encoding: gzip` included, unchanged.
> `_load` reconstructs an `httpx.Response` from that stale header over the
> now-plaintext body; something downstream (httpx's own decoder, or the
> `anthropic` SDK's response handling) sees `gzip` and tries to
> decompress content that no longer is, and the SDK maps that decode-layer
> failure to `APIConnectionError` — which is why every failure was reported
> as a "connection" problem with `$0` cost (nothing was ever dispatched to
> the network on a replay branch; the failure is purely local, before any
> request leaves).
>
> This bug is not new — `record_if_missing` shipped in this file's own §M6
> Deviation 5, tested only against `httpx.MockTransport`-fabricated
> responses (`tests/test_validity_cassette_plumbing.py`,
> `tests/test_cassettes.py`), which never set `content-encoding` in the
> first place. **Tonight was the first time `record=True` ever ran against
> the real API**, so this had never been exercised until now. Confirmed
> definitively: `match_key()` recomputed from each cassette's own recorded
> request fields matches its filename for all 46 (not a key-mismatch/cache-
> miss problem either) — the replay branch is reached correctly and fails
> inside it, every time, for every cassette.
>
> **Left open, not fixed tonight, on explicit instruction:**
> - `CassetteCore._write`/`_load` (`sul/providers/cassette.py`) need to
>   reconcile the stored (decompressed) body with the stored (still-
>   compressed-claiming) headers — most likely by stripping
>   `content-encoding` (and probably `transfer-encoding`, `content-length`,
>   which are equally stale against a re-encoded plaintext body) at write
>   time, since the cassette always stores plaintext regardless of what the
>   wire used. Whoever picks this up should re-run the offline diagnostic
>   above against a fix before attempting Config B again — no live call is
>   needed to verify it, only the 46 cassettes already on disk.
>   **Fixed the same session, once §M6's own acceptance criterion turned out
>   to depend on it — see Deviation 13 below.**
> - `sul.runner.orchestrator._run_one_persona`'s per-run containment still
>   only catches `(BudgetExceeded, StructuredOutputError)`, not
>   `ProviderError` generally (carried over from Deviation 11's own "not
>   done" note above) — real either way, independent of the cassette bug,
>   and also not fixed tonight.
> - `run_validity_harness`'s `max_cost_usd` was unbounded in this recording
>   pass; that was an oversight, not the intent. `scripts
>   /record_validity_cassettes.py` now takes `--max-cost-usd` (default
>   `$1.00` per check — discriminative validity spends it twice, once per
>   artefact study; acquiescence and position bias each get their own; see
>   the flag's own `--help` text) rather than leaving it unset.
> - `docs/limitations.md`'s template gained a standing, unconditional
>   section (survives every `sul validate` regeneration, since it is not
>   derived from the `FakeProvider`-only `ValidityReportModel` `sul
>   validate` always builds) pointing at `tests/cassettes/` and stating
>   plainly that Config A's real numbers are Sonnet-Analyst-specific and do
>   not transfer to a cheaper or different model combination — Config B
>   remains open, and §M6's acceptance does not require it.
>
> Config B is **not required for M6's own acceptance criteria** (§M6:
> "validity report generated end-to-end offline"; the real-provider
> recording pass has always been the explicitly-separate, explicitly-
> authorised path this note and Deviation 5 describe). Committing Config A's
> 46 cassettes as-is, with Config B left open, is a deliberate choice made
> with the person running this project, not a shortfall against this
> section's acceptance line.
>
> **Amended the same session: Deviation 12's "left open" call turned out to
> be wrong on reflection — see Deviation 13.** Committing 46 cassettes whose
> own real numbers `docs/limitations.md` now describes, while `make
> validate` can no longer regenerate them from what's on disk (replay was
> broken), put a claim in the repo the code couldn't reproduce — a direct
> violation of this section's own acceptance line ("validity report
> generated end-to-end offline"), not a separate, deferrable concern the way
> the *other* Deviation 12 open item (`_run_one_persona`) genuinely is.
>
> **Deviation 13 (same session): the cassette-replay bug fixed; the missing
> test added; Config A's real numbers are now reproducible from the repo,
> not just asserted in prose.** `sul.providers.cassette.CassetteCore._write`
> now drops `content-encoding`, `content-length`, and `transfer-encoding`
> from the stored response headers (`drop_stale_response_headers`, applied
> after `scrub_headers`) — all three describe the *wire* representation of
> the original response, and `_write` has only ever stored the already-
> decompressed `response.text`, never the compressed bytes; keeping those
> headers made the cassette's own metadata lie about its own body. Storing
> raw compressed bytes instead (the other option) was rejected: cassettes
> are deliberately human-readable JSON text end to end (`_write` writes
> `json.dumps(..., indent=2)`, and `tests/test_real_cassette_scrubbing.py`
> scans the raw file *text* for credential leaks) — binary payloads would
> need base64 wrapping, defeating both. The already-committed 46 cassette
> files were migrated in place (same script logic, run once by hand — a
> pure local rewrite of `response.headers`, no cassette content or `request`
> field touched, so `match_key()` still recomputes identically); all 46
> re-verified to replay cleanly with the same offline poison-pill-transport
> diagnostic Deviation 12 used to *find* the bug in the first place.
> `tests/test_cassettes.py` gained a direct regression test
> (`test_a_gzip_encoded_response_replays_correctly`): the one `MockTransport`
> fixture in that file that actually sets `content-encoding: gzip` on a
> *really* gzip-compressed body — every fixture before it returned an
> uncompressed synthetic response, which is exactly why this bug shipped
> invisibly through every cassette test written before tonight.
>
> **The test that should have existed before the cassettes were committed:**
> `tests/support/run_recorded_validity_report_script.py` (mirroring
> `tests/support/run_report_script.py`'s cross-process pattern exactly, for
> `sul.report`'s own reason — a same-process "render twice" check cannot
> catch a wall-clock/iteration-order defect, and §M6.2 clusters *real*
> Analyst findings from these cassettes, exercising `sul.analysis
> .clustering`'s own documented order-sensitivity for the first time against
> non-synthetic input) replays all 46 cassettes as Config A
> (`record=False` — a miss is a hard `CassetteMissError`, never a silent
> live dispatch) and renders the validity report.
> `tests/test_validity_cassette_report_determinism.py` runs that script
> twice under different `PYTHONHASHSEED`, asserts the two runs are
> byte-identical, and asserts the result equals a new committed file,
> `docs/validity_report_recorded.md` — Config A's real, cassette-backed
> report, generated the same way and committed alongside `docs
> /validity_report.md`'s always-`FakeProvider` counterpart. A second
> assertion checks `discriminative_validity`/`acquiescence_bias`
> /`position_bias`/`known_answer_calibration` all come back `measured`
> directly from the harness's own `MeasurementStatus`, not inferred by
> string-matching the rendered markdown.
>
> **What the real numbers say, now that they're reproducible and not just
> asserted:** bad-artefact blocker/confusion count 6 vs. good-artefact 0
> (material difference: `True`) — discriminative validity holds up against a
> real Sonnet Analyst. Known-answer calibration: 1/3 seeded defects detected
> (`missing-email-label` caught; `dead-plan-details-link` and
> `price-contradiction` missed). Acquiescence gap: 1.0 (maximal, on this
> 5-persona panel, this seed, this framing pair) — a real, measured signal
> that the panel's replies tracked question framing here, not something to
> read past as expected/neutral. Position bias: shift 0.0 — no measurable
> position effect on this panel. None of these numbers are estimated or
> extrapolated for the CV-bullet placeholders in §7 below; §7 still says
> `[X]` deliberately; filling those in is a documentation task for whoever
> writes the README (§M8), not something to backfill here.
>
> **Amended the same session: `docs/validity_report_recorded.md` and
> `tests/support/run_recorded_validity_report_script.py` (both described
> immediately above) were deleted, superseded by the amended Deviation 5.**
> Committing a *second*, differently-named report file whose real numbers
> duplicated what `docs/validity_report.md` — the file `sul validate`
> itself writes — should have been carrying directly was the wrong shape
> for this fix: it left the file a reader actually opens still reporting
> `NOT MEASURED OFFLINE` for four checks a file beside it said were
> measured. Deviation 5 (amended, above) makes `sul validate` pick up
> `tests/cassettes/` automatically instead, so `docs/validity_report.md`
> carries the real numbers directly and there is only ever one committed
> validity report. `tests/support/run_sul_validate_script.py` replaced the
> deleted script — it drives the real `sul validate` command (via
> `CliRunner`, not a hand-rolled reimplementation of provider selection) —
> and `tests/test_validity_cassette_report_determinism.py` now asserts
> cross-process byte-stability against `docs/validity_report.md` itself.
> The real numbers reported two paragraphs up are unchanged by this
> amendment; only which committed file carries them changed.
>
> `_run_one_persona`'s per-`ProviderError` containment gap (Deviation 11's
> and Deviation 12's own "not done" note) is **not** fixed by this
> deviation, and stays open — see the carry-forward note at the top of §M7
> below. It is unrelated to the cassette bug above (it never actually fired
> during either the failing runs' persona dispatch *or* the fix's own
> verification, since replay-only diagnostics never touch `run_study`) and
> remains real, independent, unfixed.

---

### M7 — Interface and packaging

> **Carried forward from §M6 (Deviations 11–13), not yet fixed:**
> `sul.runner.orchestrator._run_one_persona`'s per-run exception handling
> only catches `(BudgetExceeded, StructuredOutputError)`, never
> `ProviderError` generally. A persona whose real dispatch fails on
> anything else (`RateLimited` exhausted, `Refused`, `BadRequest`,
> `Overloaded`, a raw `APIConnectionError`) leaves its `Run` row stuck
> wherever it was (never marked `FAILED`, no `error` recorded) and its
> `asyncio` task is never cancelled — found live during the §M6 recording
> pass (misdiagnosed there as the root cause of a failure that was actually
> a cassette bug, Deviation 12/13; this gap is real independent of that).
> Not part of this section's own scope as written; flagged here as the
> nearest natural checkpoint to pick it up before it's forgotten.

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
