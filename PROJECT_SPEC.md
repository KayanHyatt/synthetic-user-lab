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
>   **Fixed in a later session — see Deviation 17 (§M7).**
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
>   **Config B recorded in a later session — see Deviation 18 below. This
>   template paragraph's own wording is deliberately not yet updated to
>   describe it — pending review of where the comparison belongs.**
>
> Config B is **not required for M6's own acceptance criteria** (§M6:
> "validity report generated end-to-end offline"; the real-provider
> recording pass has always been the explicitly-separate, explicitly-
> authorised path this note and Deviation 5 describe). Committing Config A's
> 46 cassettes as-is, with Config B left open, is a deliberate choice made
> with the person running this project, not a shortfall against this
> section's acceptance line.
>
> **Deviation 18 (a later session): Config B recorded successfully; the
> "B is A with the Analyst swapped" claim holds, evidenced by a number, not
> asserted.** `scripts/record_validity_cassettes.py` was re-run for real
> against the same `tests/cassettes/`, once §M7 Deviation 17's own note
> confirmed the real, root cause of Deviation 12's `APIConnectionError` was
> Deviation 13's gzip-header bug — fixed and replay-verified at `ac5774e`,
> but never exercised against a live dispatch until this run (the first
> real network call to succeed from this repo since that fix). Result:
> **Config A wrote 0 new cassettes** (every one of its 46 requests replayed
> — confirms no key-mismatch drift since Deviation 12/13, and that this run
> couldn't have confounded Config B's own count), **Config B wrote exactly
> 10** (matching Config A's own recorded Analyst-call count from Deviation
> 12 exactly — 10 Sonnet Analyst calls there, 10 Haiku Analyst calls here),
> **56 cassette files total on disk.** Real spend this run: **$0.0128**
> (10 fresh `claude-haiku-4-5` Analyst calls; every Persona/Moderator/probe
> request replayed at $0, as the script's own docstring predicted). One new
> cassette was inspected by hand: `"model": "claude-haiku-4-5-20251001"` in
> the request, a clean `{"findings": [...]}` body, `200`, no stale
> `content-encoding` header — Deviation 13's fix holds on a fresh write, not
> just on the 46 migrated-in-place files it was originally verified against.
>
> **All four Config B section statuses: `measured`.** No
> `PARTIALLY_MEASURED` anywhere in either config this run.
>
> **Scrubbing gate, run before committing, against the real 56-file
> directory (not the empty one `tests/test_real_cassette_scrubbing.py`'s own
> docstring still describes):** all 3 assertions in that file passed for
> real, not vacuously. Independently, the 10 new files were grepped by hand
> for the `sk-ant-` prefix, for credential header names
> (`x-api-key`/`authorization`), and for the last 8 characters of the live
> configured key — zero matches on all three.
>
> **`sul validate` is unaffected, confirmed both structurally and
> empirically.** `src/sul/cli.py::_select_validate_provider` always
> constructs its replay-only provider with `_CASSETTE_CONFIG_MODEL`/
> `_CASSETTE_CONFIG_ANALYST_MODEL` (Haiku/Sonnet — Config A's own
> combination) regardless of what else is on disk, so `match_key()`
> (embeds the request's `model` field) can never route it to a
> Haiku-Analyst cassette. `.\make.ps1 validate` was re-run after this
> session's recording pass: `docs/validity_report.md`'s SHA-256 is
> unchanged, and `git diff` against both `docs/validity_report.md` and
> `docs/limitations.md` is empty —
> `tests/test_validity_cassette_report_determinism.py`'s own byte-identical
> guarantee holds against the now-56-file directory, not just the original
> 46.
>
> **One-line self-contradiction fixed in the same commit:**
> `sul.validity.harness.run_validity_harness`'s own docstring said
> `max_cost_usd` "can together spend up to roughly 3x it" while two lines
> above stating discriminative validity alone spends it twice (once per
> artefact study) — three call sites, one doubled, is four independent
> budget guards, not three. Now reads "roughly 4x", matching the arithmetic
> stated two lines above it, not contradicting it.
>
> **What Config B is not, yet:** these 10 cassettes exist and replay
> cleanly, but nothing in `sul validate`'s own path reads them (by design —
> see above), and no Haiku-vs-Sonnet Analyst comparison has been written up
> anywhere in this repo's prose. That is deliberately a separate step,
> pending its own review. **Written in a later session — see Deviation 20
> below (the composition-hole fix) for what the comparison actually
> found, and the two prose sites (`limitations.md.j2`, README's
> Claim-trace table) for where it was written up.**
>
> **Deviation 19 (a later session): `DiscriminativeValiditySection` and
> `KnownAnswerCalibrationSection` had no completion denominator, unlike
> `AcquiescenceSection`/`PositionBiasSection` — closed.** Found while
> proving Deviation 18's 10 Config B cassettes complete: hiding one
> genuinely-needed cassette by hand still produced `discriminative_
> validity: measured` with an unchanged `bad_blocker_confusion_count`,
> because `_run_one_persona`'s per-run containment (§M7 Deviation 17)
> silently marks just the affected persona's `Run` `FAILED` and the
> section finishes on whatever remains — a confident integer over fewer
> personas than were actually attempted, with nothing to signal it.
> **Deviation 17's containment is what made this reachable — that
> interaction is the finding, not the missing field.** Before Deviation
> 17, the same failure propagated out of `run_study` uncaught and was
> caught by `run_validity_harness`'s own section-level
> `except (ProviderError, StructuredOutputError)`, which correctly
> degraded the *whole section* to `PARTIALLY_MEASURED`; moving containment
> down to the per-run boundary (the right fix for its own stated reason —
> a persona should not be able to take out siblings or the whole study)
> removed the one thing that used to catch this.
>
> `DiscriminativeValiditySection` gained two independent denominator pairs
> (`bad_personas_attempted`/`bad_personas_completed`,
> `good_personas_attempted`/`good_personas_completed` — two, not one,
> because discriminative validity runs two independent panels, unlike
> acquiescence/position's single subject pool), sourced from the
> `StudyRunSummary` that `run_artefact_study`
> (`sul/validity/runs.py:113-122`, `ArtefactStudyRun`) already received
> from `run_study` and discarded entirely — not recounted from `Run` rows.
> `KnownAnswerCalibrationSection` gained one pair,
> `personas_attempted`/`personas_completed`, **inherited from the
> bad-artefact study rather than computed independently** — it reads
> `discriminative_result.bad_rows` directly (`harness.py:276-277`, the
> identical row set), so a bad-artefact dropout affects both sections
> identically; two sections disagreeing about the same panel would be
> worse than the hole this closes. Any dropout on either artefact degrades
> the whole `DiscriminativeValiditySection` to `PARTIALLY_MEASURED` (no
> tolerance threshold — the denominator printed beside the count is the
> disclosure; where it stops being useful is the reader's call).
> `sul.validity.harness._probe_status` is reused as-is for the per-artefact
> three-way status decision, called once per artefact and combined; its
> own `reason` text is discarded when `PARTIALLY_MEASURED`, since that
> wording ("subjects... completed every probe call") is written for
> §M6.3/§M6.4's single-shot probe calls and would misdescribe a §M6.2
> turn-loop persona run — `sul.validity.sentinel
> .partially_measured_personas_reason` is its sibling, not a
> generalisation of it.
>
> **Negative control, permanent
> (`tests/test_validity_discriminative_completeness.py`), shown red before
> the fix, against a `tmp_path` copy of the real cassette directory — the
> committed `tests/cassettes/` is never mutated.** The Sonnet Analyst
> cassette for the one bad-artefact persona whose transcript escalates
> across four turns (identified by grepping the committed cassettes for
> that persona's own `blocker` finding text, not guessed) was deleted from
> the copy. Pre-fix: `discriminative_validity.status == MEASURED`,
> `bad_blocker_confusion_count == 4` (silently changed from 6, confidently
> reported, no denominator). Post-fix: `PARTIALLY_MEASURED`,
> `bad_personas_attempted=5`, `bad_personas_completed=4`,
> `good_personas_attempted=good_personas_completed=5`,
> `known_answer_calibration` degrades the same way with the same
> denominator.
>
> **Deviation 20 (same session, same chain, recorded separately — a
> different mechanism from Deviation 19's): `bad_blocker_confusion_count`/
> `good_blocker_confusion_count` are sums, and a sum hides its own parts.**
> Found by the finding-row comparison Deviation 18's own "what Config B is
> not, yet" note deferred: Config A and Config B's bad-artefact aggregate
> (6 vs 0, material difference `true`) is identical in both configs, but
> the `Finding` rows behind it are not. Config A: 8 findings — `{blocker:
> 1, confusion: 5, missing_info: 2}` — including one severity-4 `blocker`
> ("felt stuck and unable to proceed") anchored at 5 distinct (turn
> ordinal, category) positions across one persona's four-turn escalation.
> Config B, replaying the identical transcript: 7 findings — `{confusion:
> 6, missing_info: 1}` — **zero `blocker` findings**, anchored at only 2
> distinct positions. Reclassifying Config A's one `blocker` as `confusion`
> moves an item between the two categories the metric sums and leaves the
> sum unchanged (1+5 = 0+6 = 6) — the two configs did not agree; the metric
> could not disagree. On the good artefact, both configs report 0 (all
> `delight`), but Config A's Sonnet Analyst emitted a finding for only 2 of
> 5 personas while Config B's Haiku Analyst emitted one for all 5 —
> reticence about flagging nothing, not a category or severity difference,
> since 0 is exactly the number a broken Analyst also produces and this
> confirms it wasn't one.
>
> **The fix is disclosure, not redefinition — `bad_blocker_confusion_count`/
> `good_blocker_confusion_count` still compute exactly what they always
> did.** Summing `blocker`+`confusion` remains defensible as the headline
> "does the panel separate a bad artefact from a good one" metric; changing
> it would silently invalidate every committed number, including Config
> A's own. `DiscriminativeValiditySection` gained
> `bad_category_counts`/`good_category_counts` (a `dict[str, int]`, every
> category present in that artefact's findings, not just the two the
> headline sums) and `bad_distinct_anchor_count`/`good_distinct_anchor_count`
> (the count of distinct (turn ordinal, category) positions, collapsed
> across personas — coverage of the transcript, not a second finding
> count), computed purely in memory from `discriminative_result.bad_rows`/
> `good_rows` (`Finding.category`/`.severity`/`FindingRow
> .evidence_turn_ordinal` were already resolved by `load_finding_rows`'s
> existing join — zero new queries) via
> `sul.validity.discriminative.category_counts`/`.distinct_anchor_count`.
> Rendered beside the existing headline number in both
> `validity_report.md.j2` and `limitations.md.j2`, the same place the
> Deviation 19 denominators render.
>
> `.\make.ps1 validate` was re-run after both fixes; the diff against
> `docs/validity_report.md`/`docs/limitations.md` is purely additive —
> every existing number (`6`, `0`, `True`, `1/3`, `0.3333333333333333`)
> unchanged, only denominators and composition breakdowns appended beside
> them.
>
> **The Haiku-vs-Sonnet Analyst comparison itself, written up in the two
> agreed places, once this section's own composition fields made it
> possible to cite a denominator instead of a bare aggregate.** Backed by
> a committed, regenerable test, not scrollback — `tests/test_validity
> _cassette_report_determinism.py::test_config_b_numbers_are_reproducible
> _and_complete` was extended with the exact composition values asserted
> (`bad_category_counts == {"confusion": 6, "missing_info": 1}`,
> `bad_distinct_anchor_count == 2`, against Config A's own committed
> `{blocker: 1, confusion: 5, missing_info: 2}` / 5, both in
> `docs/validity_report.md`) before either prose site was written, exactly
> to avoid reintroducing Deviation 13's own defect shape (a claim the repo
> asserts but cannot regenerate). `src/sul/validity/templates
> /limitations.md.j2`'s "do not transfer down a model tier" paragraph
> gained one sentence naming the measured delta and citing that test,
> regenerated via the real `sul validate` path (`docs/validity_report.md`
> untouched, confirmed by diff — the sentence lives only in
> `limitations.md.j2`/`docs/limitations.md`, never
> `docs/validity_report.md`, per this project's own standing rule since
> `docs/validity_report_recorded.md` was deleted for exactly that).
> README's now-answered "Run a second Analyst configuration before
> citing..." bullet was removed from "What I'd do differently" and
> replaced by a Measured Claim-trace row citing the same test; the
> existing "Discriminative validity 6 vs 0" and "Known-answer calibration
> 1/3" Claim-trace rows gained their own denominators in the same pass
> ("6 vs 0 over 5/5 personas per artefact" / "1/3 (5/5 bad-artefact
> personas)") — strictly stronger claims on the same evidence, not new
> ones. The comparison is scoped throughout to what was actually run: one
> panel, 5 personas, one seed, one artefact pair, this Haiku Analyst on
> this transcript — never phrased as a general property of either model.
>
> **Deviation 21 (a later session): the README paragraph the Deviation 20
> prose landed 170 lines below was never updated, and shipped self-
> contradictory in the same commit (`95551f0`) — fixed, and the docs-claim
> test that should have caught it fixed too.** `README.md`'s "Measured
> limits" section still read "there is no A/B Analyst comparison, and a
> second configuration ('Config B') was never recorded" — true when
> originally written, false since `3006b9f`, and directly contradicted by
> the Claim-trace row the same commit added further down. Rewritten to
> say what is now true without restating the Claim-trace row's own
> numbers: Config B was recorded and compared on discriminative validity
> specifically, the comparison is scoped to one panel/one seed/one
> artefact pair, and it doesn't extend to the other three checks or to
> cheaper/different model combinations generally — narrower than both the
> old denial and a blanket claim of validation, since Config B held the
> aggregate and lost the `blocker` label (see Deviation 20).
>
> **`tests/test_docs_claims.py::test_readme_config_b_claim_agrees_with
> _whether_the_cassettes_exist`, modelled on the Docker packaging check —
> and the seventh instance of this project's own recurring failure mode:
> a test that passes on its first run, for the wrong reason, because
> nobody insisted on seeing it fail first.** Detects Config B by parsing
> each cassette's request body for `model: claude-haiku-4-5` combined with
> `_RunAnalystFinding` (the Analyst structured-output schema's own marker,
> distinctive to that one call site — verified against exactly the known
> 10 Config B files and none of the other 46), not a raw file count,
> which would pass for an unrelated reason if the directory ever grew
> again. Written against the *unmodified*, still-stale README as
> instructed, it **passed** — the wrong result, silently: its exact
> multi-line substring match spanned a markdown line-wrap in the actual
> README source (the claim's own sentence wraps mid-phrase) and matched
> neither branch, so `never_recorded_claim_present` came back `False` and
> the assertion happened to hold by accident. Caught only because the red
> run was insisted on rather than assumed; fixed by whitespace-normalising
> the README text before the substring check, the same technique this
> file's own `test_every_backtick_path_named_in_the_readme_exists`
> tolerates line-wrapped `` `paths` `` with. Re-run against the same
> unmodified README: genuinely red (`assert not True`). Green only after
> the README paragraph above was actually rewritten.
>
> **One clause on the `limitations.md.j2` "do not transfer down a model
> tier" paragraph, backed by a new test rather than left as prose derived
> from deleted scratch diagnostics.** The bad-artefact and good-artefact
> comparisons (this deviation and Deviation 20) tell one story: the
> difference between the two Analysts on this transcript is categorical,
> not about severity. Both configs' two severity-4 findings on the bad
> artefact are identical in *count* but not in *category* — Config A:
> `{blocker, missing_info}`; Config B: `{confusion, missing_info}`, zero
> `blocker` at any severity — and the middle mass shifts down (mode
> severity 3 → 2: Config A `{2: 1, 3: 5, 4: 2}`, Config B
> `{1: 1, 2: 4, 4: 2}`). On the clean artefact both Analysts report
> `delight` exclusively (100% either config — the 0 blocker/confusion
> figure is well-supported, not a silent-Analyst artefact), but Config A's
> Sonnet Analyst reported *something* for only 2 of 5 personas where
> Config B's Haiku Analyst reported for all 5 — so Sonnet's bad-vs-good
> swing (8 findings → 2) is volume and category together, Haiku's
> (7 → 5) is almost purely category, because it says something about the
> artefact regardless of whether it's good or bad. None of this was
> previously asserted anywhere a future regeneration could check —
> `tests/test_validity_config_ab_severity.py` (new) calls
> `run_discriminative_validity` directly against the real cassettes for
> both configs and asserts the severity distributions, the sev-4 category
> sets, and the good-artefact persona-coverage counts above; single-process,
> not cross-process, since none of `Finding.severity`/`.category` counting
> touches `sul.analysis.clustering`'s own order-sensitive path (that risk
> is specific to cluster *labels*, which discriminative validity's
> aggregate counts never compute). `.\make.ps1 validate` re-run after the
> template edit: `docs/validity_report.md` unchanged (confirmed by empty
> diff), `docs/limitations.md` carries the new clause.
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
> remains real, independent, unfixed. **Fixed in a later session — see
> Deviation 17 (§M7).**

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
> **Fixed in a later session — see Deviation 17, further below in this
> section.**

- Typer CLI: `sul personas sample`, `sul run`, `sul report`, `sul cost`,
  `sul validate`.
- FastAPI + Jinja/HTMX dashboard: study list → run list → transcript view →
  report view. Read-only is fine.
- Dockerfile + docker-compose. `make demo` runs a complete study with
  `FakeProvider` and no API key.

**Acceptance:** fresh clone → `docker compose up` → `make demo` → dashboard shows
a completed study with report, **without any API key set**. This matters: a
reviewer with no keys can still see it work in 60 seconds.

> **M7 is partially complete. The container half of this section's own
> acceptance criterion is unmet, deliberately not redefined around, and left
> open — not silently dropped.** Everything else in this section is done and
> tested: the remaining Typer CLI (`sul personas sample`, `sul run`,
> `sul demo`, `sul dashboard`, alongside the already-landed `sul cost`/
> `sul report`/`sul validate`), the FastAPI + Jinja/HTMX dashboard, and
> `make demo`. `.\make.ps1 check` is green (324 tests, up from 263 at
> `7aba273`) and `.\make.ps1 demo` runs end to end against this repo's own
> real, persisted `sul.db` — not just a scratch pytest fixture. **No
> `Dockerfile`, `docker-compose.yml`, or `.dockerignore` were written this
> session**, on explicit instruction, after this machine turned out to have
> no Docker runtime at all: no `docker` on `PATH` in either PowerShell or Git
> Bash, no `C:\Program Files\Docker` install directory, and `wsl -l -q`
> reports zero installed distributions (Windows 11 **Home**, which has no
> Hyper-V backend alternative to WSL2). A committed-but-never-built Dockerfile
> is worse than no Dockerfile: nothing catches it lying. "fresh clone →
> `docker compose up`" therefore cannot be demonstrated on this machine as
> written, and per `CLAUDE.md`'s own rule ("If a milestone's acceptance
> criteria cannot be met as written, stop and say so rather than redefining
> them"), this stops and says so rather than quietly narrowing §M7 to "the
> parts that don't need Docker."
>
> **What remains, for whichever session has a real Docker runtime:** write
> `Dockerfile` + `docker-compose.yml` + `.dockerignore`, then execute the
> verification plan below — none of it needs re-deriving, all of it was
> worked out in this session's own Phase 0 report before Docker's absence was
> confirmed:
>
> 1. **Cold build from a fresh clone, not the working tree.** `git clone .
>    <tmp>` at whatever `HEAD` is by then, then `docker build --no-cache -t
>    sul:m7 <tmp>`. Cloning proves the image needs only tracked files, and
>    separately proves `.dockerignore` isn't papering over an untracked
>    `.env` — see point 4.
> 2. **TLS, in order of preference, never `verify=False`:**
>    - Try the plain build first. The host's TLS interception is applied by
>      software on the host; whether it reaches the container's own egress
>      depends on where that interception sits, and this is a ten-minute
>      experiment, not an assumption — it may simply work.
>    - If it fails: the container inherits **neither** `SSL_CERT_FILE` nor
>      the Windows root store — both are host-side configuration (`CLAUDE.md`'s
>      own environment note), invisible inside any container regardless of
>      how the image is built. `C:\dev\certs\windows-roots.pem` (the file
>      `SSL_CERT_FILE` already points at on this host) is the input to
>      whatever CA step the Dockerfile ends up needing: `COPY
>      windows-roots.pem /usr/local/share/ca-certificates/host-roots.crt` +
>      `RUN update-ca-certificates`, **in the build stage only**, with
>      `SSL_CERT_FILE` pointed at the resulting system bundle for `uv`. The
>      runtime stage inherits neither the `.pem` nor the env var — a runtime
>      image that trusts a corporate MITM root is a worse artefact than one
>      that simply can't reach the network, and the runtime image needs no
>      egress at all (§M7's dashboard is read-only, `FakeProvider` has no
>      transport).
>    - Escape hatch if in-container TLS still can't be resolved:
>      `uv export --frozen` on the host into a wheelhouse (`uv pip
>      download`), `COPY wheels/` into the image, `uv pip install
>      --no-index --find-links=/wheels`. Zero network at build time, which
>      sidesteps the question entirely — fallback, not default.
>    - Never `verify=False`, `--trusted-host`, `PIP_TRUSTED_HOST`, or
>      `UV_INSECURE*`, in the container or out of it.
> 3. **`uv sync --frozen`** against the committed `uv.lock` — the build must
>    resolve nothing, so it can't install a different `scikit-learn` than the
>    one embedded in every `ReportModel`'s own provenance.
> 4. **Secrets-in-image check, three ways, knowing what each one catches:**
>    a build-context check (`.dockerignore` applied to the repo's own file
>    list, asserting `.env`/`sul.db`/`.venv/`/`*.pem` excluded and
>    `src/sul/web/static/htmx.min.js` included — this one needs no Docker and
>    can be written and run *before* Docker exists, so it should land in the
>    same session as the Dockerfile, not deferred); a final-filesystem check
>    (`docker run --rm sul:m7 sh -c '...'`, which would miss an add-then-delete
>    layer); and a `docker save`-and-extract layer scan for `.env`, `sk-ant-`,
>    `*.db` across every layer tarball (the one that catches add-then-delete).
>    No `ARG`/`ENV` for any API key anywhere in the Dockerfile — those persist
>    in `docker history` in plaintext regardless of any later `RUN rm`.
> 5. **Run-time network independence:** `docker run --network none -p ...` —
>    every dashboard page must still serve. Stronger than auditing templates
>    for `<link>`/`<script src>` tags by hand, and it's the assertion this
>    project would actually want to trust.
> 6. **The acceptance chain itself, timed, with `ANTHROPIC_API_KEY` unset in
>    the invoking shell:** `docker compose up -d` → `curl 127.0.0.1:8000` →
>    `.\make.ps1 demo` on the host (the host, not `docker compose exec` — the
>    acceptance chain names `docker compose up` *before* `make demo`,
>    implying the container is already up and watching a bind-mounted
>    database the host process writes into) → reload the dashboard → confirm
>    the study, its runs, a transcript, and the report all render.
>
> Design decisions this session left for that one, rather than inventing
> them now without a way to verify them: whether the container's database is
> a bind-mounted directory or a named volume; the exact publish binding
> (`127.0.0.1:8000:8000`, not bare `8000:8000`, was this session's
> recommendation, argued in Phase 0, but never exercised end to end); and
> whether the image ships `tests/cassettes/` (needed so `sul validate`
> in-container doesn't silently fall back to `FakeProvider` — §M7 5.4 below
> covers why). None of these change what was actually built and tested this
> session; they're packaging decisions, not interface ones.

---

> **§M7 packaging criterion: MET.** Docker Desktop 4.87.0 (engine 29.7.2,
> compose v5.4.0) was installed and verified on this machine this session
> (`hello-world` ran clean); `Dockerfile`, `docker-compose.yml`, and
> `.dockerignore` are committed at the repo root, and the full six-step
> verification plan above was executed against them, plus the anti-vacuity
> checks below. `.\make.ps1 check` is green: **343 tests**, up from 337 at
> `79a80bd` (+5 `tests/test_docker_build_context.py`, +1
> `tests/test_docs_claims.py`).
>
> **Base images, pinned by digest (never a floating tag):**
> `python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134`
> and `ghcr.io/astral-sh/uv@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1`
> (uv 0.12.5), both resolved via `docker pull` + `docker inspect` this
> session.
>
> **Step 1 (cold build).** `git clone . <tmp>` at `79a80bd`, confirmed
> `HEAD` and a clean `git status` in the clone. The clone alone has no
> `Dockerfile` yet (uncommitted at clone time) — the packaging files were
> staged into the clone for this session's iteration, and a second, truly
> clean `git clone . <tmp>` + `docker build --no-cache` was run again
> *after* this commit, against the committed `HEAD`, as the actual proof
> the criterion names — see the timestamped output below.
>
> **Step 2 (TLS).** The plain build succeeded on the first try, `--no-cache`,
> from the fresh clone — no CA-copy step, no wheelhouse fallback needed.
> `synthetic-user-lab==0.1.0 (from file:///app)` in the `uv sync` output
> confirms the editable install resolved with zero network trust workaround.
>
> **Step 3 (`uv sync --frozen`).** Ran against the committed `uv.lock`,
> `--no-dev`, resolving nothing (`--frozen`).
>
> **Step 4 (secrets-in-image, three ways, each demonstrated by breaking it):**
> - *Build-context check*: `tests/test_docker_build_context.py`, a
>   pure-Python re-implementation of Docker's `.dockerignore` matching
>   rules, run offline. **Cross-checked once against real Docker**: a
>   throwaway `COPY . /ctx` image's actual build-context file list (`find`
>   inside the container) was diffed against the Python model's output on
>   the same repo — 193 files, byte-identical file sets (after normalizing
>   Windows CRLF from the Python side). This surfaced a real leak the model
>   didn't originally predict: 81 stray `__pycache__/*.pyc` files from local
>   `pytest`/`mypy` runs rode along with the broad `!src/**` re-inclusion.
>   Fixed by appending `**/__pycache__/`, `**/__pycache__/**`, `**/*.pyc` to
>   `.dockerignore` (order matters — Docker's last-match-wins rule requires
>   these *after* the re-inclusion lines); re-verified identical (112 files,
>   both sides) after the fix. `.dockerignore` is a deny-by-default
>   whitelist (`*` then explicit `!src/`, `!configs/`, `!artefacts/`,
>   `!pyproject.toml`, `!uv.lock`), not the blacklist form first sketched —
>   structurally closes the "entry that looks like it excludes a secret but
>   doesn't match" class for files that don't exist yet, at the cost of
>   needing every legitimately-needed path re-included explicitly.
> - *Break-then-fix, working tree (not the clone — a fresh clone has no
>   `.env` at all, so a clean scan there would prove nothing)*: appended
>   `!.env` to `.dockerignore`, built a minimal probe image
>   (`COPY .env /app/.env-leak-test`, `--no-cache`) — **succeeded**, and
>   `docker save` + extracting the OCI blob tarballs + grepping found the
>   real key: a genuine `ANTHROPIC_API_KEY=sk-ant-api03-...` line, extracted
>   and displayed in this session's own terminal output (not reproduced
>   here or anywhere else committed). Reverted `.dockerignore`, rebuilt the
>   identical probe — this time the build **failed outright**,
>   `COPY .env /app/.env-leak-test: "/.env": not found` — `.dockerignore`
>   keeps `.env` from ever reaching the daemon's build context at all, a
>   stronger guarantee than "the real Dockerfile just doesn't reference it."
> - *Full layer scan of the real `sul:m7` image*: `docker save` + extracted
>   all 10 layer blobs, scanned each for `sk-ant-` content and for
>   `.env`/`sul.db` filenames — **0 hits across all 10 layers**. No
>   `ARG`/`ENV` for any API key anywhere in the Dockerfile (confirmed via
>   `docker inspect .Config.Env`: only `PATH`, `LANG`, `GPG_KEY`,
>   `PYTHON_VERSION`, `PYTHON_SHA256`, `SUL_DASHBOARD_HOST`,
>   `SUL_DASHBOARD_PORT`).
>
> **Step 5 (run-time network independence) — §M7's recorded form amended.**
> `docker run --network none -p 127.0.0.1:8001:8000 ... sul:m7` does not
> fail as the recorded plan implied — Docker accepts the flag combination
> syntactically, but `docker inspect`'s `NetworkSettings.Ports` comes back
> `map[8000/tcp:[]]`: no host binding is ever created, so the published
> port is silently dead (`curl` to it: `Failed to connect`). Confirmed via
> `docker inspect .HostConfig.NetworkMode` = `none`. **Corrected form**:
> `docker exec` into the running `--network none` container and hit the
> dashboard over its own loopback with `urllib` — `/` and
> `/static/htmx.min.js` both returned `200`. Negative control in the same
> container: `urllib.request.urlopen("http://example.com")` failed with
> `Temporary failure in name resolution` — proving the isolation is real,
> not just an unexercised assertion.
>
> **Step 6 (acceptance chain, timed, `ANTHROPIC_API_KEY` unset in the
> invoking shell — confirmed empty before this run).** `docker compose up
> -d` (1s) → `curl 127.0.0.1:8000` (200, after the container finished
> starting) → `.\make.ps1 demo` **on the host** (6s; `study_id=85
> completed_runs=6 findings=13 clusters=13`) → reload
> `http://127.0.0.1:8000/` → `/studies/85/runs` (200), `/studies/85/report`
> (200, renders "Demo: bad onboarding usability study — report" with
> clusters and evidence). Total wall-clock for compose-up→reload: **8s**
> (excludes image build time, already cached from Step 1's cold build).
>
> **Design decisions resolved this session** (left open in the note above):
> - **Database**: repo root bind-mounted read-only at `/repo`,
>   `SUL_DATABASE_URL=sqlite:////repo/sul.db` — not a single-file mount (a
>   fresh clone has no `sul.db`, and Docker silently creates a *directory*
>   at a missing bind-mount source, which would break the acceptance chain
>   on exactly the machine it's meant to prove itself on) and not a named
>   volume (the container would then own a database the host's own
>   `make demo` never writes into, breaking the recorded reading of the
>   acceptance chain, which names `make demo` running on the host).
>   **Deviation**: a reviewer's own `.env`, if one exists, is therefore
>   visible inside the running container at `/repo/.env` — never in any
>   image layer, read-only, and never loaded (`pydantic-settings` reads
>   `.env` relative to the process's CWD, which is `/app`, not `/repo`).
>   Documented rather than masked with an anonymous-volume trick.
> - **Publish binding**: `127.0.0.1:8000:8000`, as recommended and now
>   exercised end to end.
> - **Cassettes**: not shipped. `tests/cassettes/` is excluded by
>   `.dockerignore`; the container can serve the dashboard and run
>   `sul demo` (constructs `FakeProvider()` directly — §M7 5.4), but not
>   `sul validate` (would silently fall back to `FakeProvider` via
>   `sul.cli._select_validate_provider`'s cassette-directory sniff, which is
>   a worse artefact than not offering the command).
> - **Entrypoint**: `SUL_DASHBOARD_HOST=0.0.0.0` set as an image-level `ENV`
>   default (the `Settings` default of `127.0.0.1` would leave the
>   published port unreachable from outside the container) — config-driven
>   via the already-existing `Settings.dashboard_host`, no source change.
> - **Non-root runtime user** (`appuser`), not previously named by this
>   section's own scope bullet — a standard hardening step for a
>   long-running, eventually-published-port process, added without being
>   asked; flagged here rather than silently folded in.
> - **Editable-install layout**: both build and runtime stages use `/app`
>   as `WORKDIR`, so `uv sync`'s editable install and `sul.demo.REPO_ROOT`/
>   `sul.config.DEFAULT_CASSETTE_DIR`'s `Path(__file__).resolve().parents[2]`
>   resolve identically in both stages — no source rewrite needed, exactly
>   as the groundwork paragraph below anticipated.
>
> **README staleness (§M7 5's own concern) closed.** `README.md`'s "no
> Docker workflow in this tree" paragraph and its claim-trace row both
> updated to reflect the committed files and the demonstrated chain.
> `tests/test_docs_claims.py` gained
> `test_readme_docker_claim_agrees_with_whether_the_files_exist`, coupling
> the README's prose to `Dockerfile`/`docker-compose.yml`'s actual existence
> in both directions — this closes *this specific* instance of "a claim
> true when written, false later, with no filesystem correlate," but not
> the general class: no offline test can assert "the cold build was
> actually run and passed" (that would need a Docker daemon and network
> access inside `pytest`, breaking the offline-tests rule outright). That
> half is recorded here, in prose, as **Demonstrated** evidence rather than
> as something any test defends — the same category `README.md`'s own
> claim-trace table already uses for exactly this reason.
>
> **Session spend: $0.00** (no LLM call made; `sul demo` used
> `FakeProvider` throughout, as it always has).

---

> **Config-driven groundwork already in place, so the eventual container
> needs no source rewrite:** `Settings.database_url` (already existed,
> `SUL_DATABASE_URL`) is the one place both `sul demo` and `sul dashboard`
> read the database location from — no hardcoded path anywhere in
> `sul.web`/`sul.demo`. `Settings.dashboard_host`/`Settings.dashboard_port`
> (new, `SUL_DASHBOARD_HOST`/`SUL_DASHBOARD_PORT`, documented in
> `.env.example`) default to `127.0.0.1:8000` and are overridable by
> `sul dashboard --host`/`--port`, so a future container's bind address is a
> deploy-time decision, not a code change. Neither `sul.web` nor `sul.demo`
> assumes `tests/` or `.env` exists at runtime.
>
> **Deviation (recorded, not re-litigated): the inherited `ProviderError`
> gap (carried forward above) stays open.** It becomes user-visible only if
> the dashboard can trigger a run; it can't — `sul.web` is strictly
> read-only, enforced at the AST level (see below), so no route ever
> constructs a `ModelClient` or calls `run_study`. `sul demo` and the CLI's
> own default (`sul run`'s `--provider` defaults to `"fake"`) both run
> `FakeProvider` exclusively, which has no transport and cannot raise
> `ProviderError` at all. The only path that can reach the gap is
> `sul run --provider anthropic`, a real dispatch a user asked for by name —
> unchanged from before this milestone, not newly exposed by it.
>
> **Amended this session (Deviation 17): the `ProviderError` gap above is
> fixed, not just recorded.** `sul.runner.orchestrator._run_one_persona`'s
> per-run exception handling now has two clauses: `except BudgetExceeded`
> (unchanged, still the sole handler of the study-wide budget-guard case),
> then `except (ProviderError, StructuredOutputError)` (new) — kept
> separate because `BudgetExceeded` is itself a `ProviderError` subclass
> (`sul.providers.budget.BudgetExceeded`), so a single broad
> `except ProviderError` would silently swallow the budget-guard case in
> the same clause and erase its documented study-wide-stop semantics. A
> persona run that fails on `RateLimited` exhausted past
> `call_with_backoff`'s retries, `Refused`, `BadRequest`, `Overloaded`, or a
> raw connection error is now marked `FAILED` with the error recorded,
> exactly like the `BudgetExceeded`/`StructuredOutputError` cases already
> were, instead of being left stuck at whatever status it last had with
> `error` still `None`.
>
> **Negative control written first, run against pre-fix `main`, shown red
> before any source change:** `tests/test_orchestrator_provider_error
> _containment.py` scripts an `Overloaded` (not `RateLimited` —
> `sul.runner.retry.call_with_backoff` deliberately never retries it, so
> one raise reaches the boundary undelayed) on the first `PersonaReply`
> dispatch of a two-persona study (`tests/fixtures/panel_2.yaml`). Against
> pre-fix `main` this failed with `run_study` propagating the raw
> `Overloaded` exception and both `Run` rows left at `(RUNNING, None)` /
> `(PENDING, None)` — the sibling persona never even started, since
> `asyncio.gather`'s default behaviour raises as soon as the first task
> fails, without waiting for (or cancelling) the others. Post-fix, the same
> test passes unmodified: the failing run ends `FAILED` with a non-empty
> `error`, the sibling ends `COMPLETED`, and `StudyRunSummary.failed`/
> `.completed` each have exactly one entry.
>
> **Behaviour change, documented in `sul.runner.orchestrator`'s own module
> docstring and in `README.md`'s "what I'd do differently" section:** a
> study-wide fatal that isn't a budget breach (a bad API key, concretely —
> confirmed via `src/sul/providers/anthropic.py`: a 401 falls through to a
> plain `ProviderError`, not one of the named subclasses) used to abort the
> whole `run_study` call on its first occurrence. It now surfaces once per
> persona instead of once per study: every persona's own first dispatch
> hits the same failure independently and is caught, so a bad key now
> produces N `FAILED` rows with the error recorded, not one crash with
> everything else left in whatever state it was in.
>
> **Not changed, on explicit instruction, pending a separate decision:**
> `run_study`'s `asyncio.gather(*...)` stays as-is rather than becoming
> `asyncio.TaskGroup`. Now that every named `ProviderError` family (and
> `StructuredOutputError`) is caught per-run, `gather`'s known gotcha — an
> unhandled exception in one task doesn't cancel still-running siblings —
> only matters for the genuinely-unexpected residual case the module
> docstring already calls "the offline analogue of the process actually
> being killed." `TaskGroup` would close that gap but raises
> `ExceptionGroup` instead of the original exception type, a breaking
> change to `run_study`'s own documented contract; deferred as a follow-up,
> not implemented here.
>
> `.\make.ps1 check` is green: **344 tests**, up from 343 at `f59a003`
> (+1, `tests/test_orchestrator_provider_error_containment.py`). No real
> provider call made this session — `ScriptedProvider` throughout. Session
> spend: $0.00.
>
> **Deviation: `sul.web` (the dashboard) is strictly read-only, enforced at
> the AST level, not just by docstring.** §M7 says "Read-only is fine" —
> this takes the stronger reading. `tests/test_agent_module_hygiene.py`
> extends its existing per-module import check (previously scoped to
> `sul/agents/` and `sul/runner/`) to every module under `sul/web/`: none
> may import `sul.runner.orchestrator` (`run_study`), `sul.providers.client`
> (`ModelClient`), or any concrete provider adapter. This is what makes an
> unauthenticated, eventually-published port defensible — there is no code
> path from the dashboard to an LLM dispatch, so there is no spend endpoint
> behind it, and §M4's budget gate never needs to reach the web tier.
>
> **Deviation: the dashboard's report view shares `sul.report.html`'s own
> cluster/evidence fragment (`sul/report/templates/_clusters.html.j2`,
> extracted from `report.html.j2`) rather than re-authoring it.** One
> escaping configuration, one markup shape — `tests/support/html_parse.py
> ::parse_report_html` (built for M5's report) parses the dashboard's report
> page unchanged. The extraction is behaviour-preserving:
> `tests/test_report_rendering.py` passes unmodified against the refactored
> template.
>
> **Deviation: `sul.web.templates` builds one hand-rolled `jinja2
> .Environment(autoescape=True)`, used by every full page and every HTMX
> partial** — not FastAPI's `Jinja2Templates` wrapper, whose default
> `select_autoescape` only turns escaping on for template names ending
> `.html`/`.htm`/`.xml`; every template in this project ends `.html.j2`,
> which that default would silently miss entirely.
> `tests/test_web_escaping.py` asserts pages and partials render through the
> *same* `Environment` object (by identity), and round-trips M5's own
> `ESCAPING_HAZARD_QUOTE` fixture (`tests/support/report_factory.py`,
> extended, not forked) through the transcript page, the report page, and
> the one HTMX partial this app serves.
>
> **Deviation: the standing caveat (`sul.report.model
> .SIMULATED_PANEL_CAVEAT`, imported not retyped) sits outside every HTMX
> swap target this app declares, checked structurally, not just rendered.**
> `tests/support/dashboard_parse.py` parses each page into an element tree
> with ancestor-id chains, resolves every `hx-target` (and self-targeting
> `hx-get`) to the element id it would overwrite, and asserts the caveat's
> own element is neither one of those ids nor a descendant of one.
> `hx-swap-oob` (the one HTMX feature that can write outside its own
> declared target) is asserted absent from every route outright, since the
> ancestor-chain check can't reason about it. Every partial also repeats the
> caveat text in its own response body, belt-and-braces, independent of the
> structural proof.
>
> **Deviation: the dashboard's database connection is driver-enforced
> read-only, not merely unused-by-convention.** `sul.web.app
> ._read_only_session` opens SQLite via a `mode=ro&uri=true` URI;
> `tests/test_web_readonly.py::test_read_only_session_cannot_write` proves an
> `INSERT` attempted directly against the read-only session raises
> `sqlite3.OperationalError` at the driver level. One engine per request,
> disposed on exit (`sul.web.app._read_only_session`'s own docstring records
> why: a leaked-engine-per-request design, tried first, hard-locked the
> `.db` file on Windows after about twenty requests — found by curling a
> real running `sul dashboard` process during this session, not by pytest
> alone, since the in-process ASGI test transport never held the file handle
> long enough to hit it). A missing database file renders an explicit empty
> state ("no studies yet — run `sul demo`") rather than a 500, tested with
> and without a `.env`/pre-existing database present.
>
> **Deviation: `htmx.min.js` (2.0.4) is vendored, not CDN-loaded.** `CLAUDE.md`
> names HTMX in the stack, and §M7's own scope bullet says "Jinja/HTMX
> dashboard" — dropping it to avoid a network dependency would have narrowed
> that bullet, which isn't this session's call to make; a CDN `<script src>`
> would defeat the eventual `docker run --network none` requirement the
> moment anyone opened the dashboard offline. Fetched once, on the host, from
> two independent CDNs (`unpkg`, `jsdelivr`) serving the same npm-published
> artefact — byte-identical, same sha256
> (`e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447`) — never
> fetched at image build time. `sul.web.static_assets` pins the version and
> hash; `tests/test_vendored_assets.py` hashes the committed file against the
> pin on every run, so an edit to the file that doesn't also update the pin
> fails loudly.
>
> **Deviation: `sul run`'s provider selection (`sul.providers.factory
> .build_provider`) is a second allow-list, deliberately separate from
> `run_validity_harness`'s own two-member one (§M6 Deviation 7).** `sul run`
> may legitimately dispatch to any real adapter a user names on the command
> line; `sul validate` must never be pointable at one by a flag at all.
> Fusing the two would widen §M6 Deviation 7's boundary — this module exists
> so that never has to happen. An unconfigured real provider fails with a
> clear, typed error (`ProviderNotConfiguredError`) naming the missing
> environment variable, not a bare exception from three layers down.
>
> **Deviation: `sul personas sample` prints, and writes nothing to the
> database.** §M3's own acceptance criterion (byte-identical output across
> two runs given the same seed) is directly checkable against stdout;
> persisting a `Panel`/`Persona` graph is `sul run`'s job (via
> `materialize_study`, as part of a real study), not a side effect a reader
> would expect from "show me what this config samples to."
> `tests/test_cli_personas_sample.py` proves both the byte-identical output
> and the no-database-write claim directly (pointing `SUL_DATABASE_URL` at a
> not-yet-existing file and confirming it still doesn't exist afterward).
>
> **Deviation (a real bug, found and fixed, not merely a design choice):
> `materialize_study` now deduplicates `Artefact` rows by `content_hash`
> before inserting, instead of always inserting and occasionally colliding.**
> `Artefact.content_hash` is `UNIQUE` and — per `sul.hashing.content_hash`'s
> own docstring — is meant as a content-address, but materialisation never
> looked one up before writing. `configs/study.demo.yaml` and `configs
> /study.example.yaml` both point at `artefacts/bad_onboarding.html`;
> running `sul demo` against this repo's own real, persisted `sul.db` (which
> already had that artefact materialised under an earlier study, from
> earlier session work) raised `IntegrityError: UNIQUE constraint failed:
> artefacts.content_hash` on the very first `sul demo` invocation this
> session, before any fix — a failure mode the pytest suite never caught
> because every test starts from an empty database. Two distinct artefact
> bodies still get two distinct rows (`tests/test_runner_config.py
> ::test_materialize_study_still_creates_distinct_artefacts_for_distinct_content`);
> two calls with byte-identical bodies now share one `Artefact` row while
> still creating two independent `Study` rows
> (`::test_materialize_study_reuses_an_existing_artefact_with_the_same_content`).
> `materialize_study`'s general non-idempotency for `sul run` (two
> *different* studies deliberately stay independent) is unchanged and is
> not what this deviation touches.
>
> **Amended in the same session: the paragraph above originally continued
> with a second mechanism, since removed.** `sul.demo.run_demo` additionally
> reused an existing `Study` row by name (`config.name`) before calling
> `materialize_study` at all, so that a repeated `sul demo` resumed the same
> demo study rather than creating a new one. Asked to justify this against
> the fix above rather than assert it, the two turned out not to be
> complementary: reverting the `Study`-by-name reuse and calling
> `materialize_study` twice directly (with the `Artefact`-level fix from
> this deviation still in place) succeeds cleanly on its own — `study_id`
> increments, `artefact_id` doesn't. The `Artefact`-level fix was already
> sufficient; the `Study`-by-name reuse was a second, narrower idempotency
> mechanism doing no correctness work, layered on top of a first one that
> already did all of it. Removed rather than kept as a documented,
> unify-later item: `run_demo` now calls `materialize_study` the same plain
> way `sul run` does, and a repeated `sul demo` creates a fresh, independent
> `Study` every time — consistent with `materialize_study`'s own documented
> contract, and with the property M6's reproducibility check depends on
> (repeated, independent materialisations of one config). Covered directly
> by `tests/test_demo.py
> ::test_run_demo_is_safe_to_call_twice_and_creates_two_independent_studies`,
> not only by hand via the CLI as the original version of this note claimed.

---

### M8 — Documentation

`README.md` with: one-paragraph what/why, architecture diagram, 60-second demo
instructions, a cost table (what a 40-persona study actually costs per provider),
the limitations section, and "what I'd do differently with real participants."

> **M8 complete. Deviations recorded below; none narrow this section's own
> six-element list, and none touch §M7's own unmet packaging criterion.**
>
> **Deviation 14 (§M8 scope).** §M8, unlike M0–M7, carries no numbered
> acceptance-criteria block — its six-element list (what/why, architecture
> diagram, 60-second demo, cost table, limitations, "what I'd do
> differently") *is* the criterion, and every element is present in the new
> `README.md`. §M8 does not own §M7's Docker packaging (§M7 named it
> explicitly and reserved it for a session with a real Docker runtime; that
> was true when this paragraph was written — this machine then had none,
> `docker` not on `PATH`, `wsl -l -q` reporting zero distributions — and is
> no longer true: §M7's packaging criterion is recorded MET further above,
> in a later session, once Docker Desktop was installed). No live API call
> was made and no report was
> regenerated from a live provider; `sul validate`'s cassette-replay path
> (§M6 Deviation 5, amended) was invoked once to refresh
> `docs/limitations.md` after Deviation 15 below, and it reproduced
> `docs/validity_report.md` byte-for-byte, as
> `tests/test_validity_cassette_report_determinism.py` already guarantees.
> Session spend: $0.00.
>
> **Deviation 15 (touches M6's surface).**
> `src/sul/validity/templates/limitations.md.j2` — and only the template,
> never the generated `docs/limitations.md` directly — gained a new section
> reporting the four provider-gated checks' own numbers (discriminative
> validity, acquiescence bias, position bias, known-answer calibration) with
> their denominators, whenever a real or cassette-backed provider actually
> measured them. Before this, `docs/limitations.md` carried reproducibility
> and the three offline-measurable clustering weaknesses only — the
> acquiescence-bias result (gap 1.0 over 5/5 subjects, this project's most
> serious measured limitation) existed solely in `docs/validity_report.md`,
> one file away from the one a reader opens expecting limitations. This is a
> burial fix, not a new measurement: the module's own `render_limitations_
> markdown` docstring is unchanged in intent — these four checks still do
> not count toward the file's own "at least two concrete, measured
> weaknesses" acceptance criterion (`tests/test_validity_rendering.py::
> test_limitations_md_states_at_least_two_measured_weaknesses` still passes,
> unmodified) — they are now simply not hidden when they exist.
> `docs/limitations.md` was regenerated from this template via the real
> `sul validate` CLI path (cassette-backed, offline, `record=False`); the
> resulting diff is additive only (30 inserted lines, 0 removed), and
> `docs/validity_report.md` did not change at all.
>
> **Deviation 16 (§7, not §M8's own list).** §7's CV bullets ("fill the
> brackets from real output — don't estimate") were filled from this
> session's real output: suite time (325 tests, ~83s), known-defect
> detection rate (1/3, kept as a fraction rather than a lossy percentage),
> and the resumable-orchestration bullet (20, §M4's own literal acceptance
> criterion). `[40]` was deliberately **not** filled — no 40-persona study
> has ever been run (largest recorded: 5 personas), and §7's own instruction
> forbids estimating it. This sits outside §M8's six-element list; recorded
> here because the instruction was project-level and its brackets were
> genuinely fillable (or, for `[40]`, genuinely and explicitly not).
> **`[40]` filled in a later session — see Deviation 22.**
>
> **Cost-table honesty note (not a deviation, a fact folded into the
> README itself):** `sul.db` records three validity-harness passes at
> **$0.112556 each, identical to six decimal places** — three live passes
> cannot agree to six decimals, so two of the three are cassette replays
> whose `ModelCall` rows carry a real dollar cost despite spending nothing.
> The README's cost table cites the single 5-persona measured basis
> ($0.052706, study 47) rather than `sul.db`'s summed total, to avoid
> repeating that inflation into a portfolio-facing number.
>
> **Deviation 22 (a later session): the first real 40-persona study —
> `configs/study.40.yaml`, study 146, `uv run sul run configs/study.40.yaml
> --provider anthropic --concurrency 5`. 40/40 personas completed, 0
> failures, $0.2104 real spend, 118 calls.** `panel.example.yaml` untouched
> (already `size: 40`). Confirmed twice: `sul run`'s own summary line
> (`personas=40 already_completed=0 completed_this_run=40 failed=0`) and an
> independent direct query of every `Run` row for `study_id=146`, all 40
> `COMPLETED`. On explicit instruction, a failure of even one persona would
> have stopped this deviation short of filling anything — §M7 Deviation
> 17's own per-run containment means a `BudgetGuard` breach or a live
> provider error now marks that one `Run` `FAILED` and the study finishes
> anyway, so a partial panel can still print a plausible-looking total; §7's
> `[40]` and the cost table both require the genuine 40-of-40 this run
> happened to produce, not a number that would look the same either way.
>
> **A different configuration from the README's existing 5-persona "measured
> basis," not an ×8 confirmation of it — stated explicitly, not left for a
> reader to assume from adjacency.** `sul run`/`StudyRunConfig` has no
> `model_by_agent` field (confirmed by reading `sul.cli.run` and
> `RunnerOptions` before proposing this config): every agent dispatches on
> one model, so this run is all-`claude-haiku-4-5` — persona, moderator,
> *and* Analyst — where the existing basis is Config A's own Sonnet-Analyst
> mix. The README's Cost section presents both as separate, individually
> labelled measurements; the original ×8-from-Config-A extrapolation
> (~$0.42, still never run for real) is **kept, not retired** — this run
> neither confirms nor refutes it, since the model mix differs.
>
> **The weak step named in the original extrapolation ("assumes every
> agent's call count scales linearly with persona count") was real, not
> idle hedging.** Linear ×8 scaling from the 5-persona basis's own 3
> Moderator / 8 Persona / 5 Analyst calls predicted 24 / 64 / 40. The real
> 40-persona run: **Analyst 40 — exact**, deterministic by construction (one
> dispatch per persona, always); **Moderator 19 and Persona 59 — both
> sub-linear**, because follow-ups depend on how often a persona reports
> confusion or gives up, and the 5-persona sample's own rate (3 of 5, 60%)
> was too small to estimate reliably — the real rate was 19 of 40 (47.5%).
> Repricing the 5-persona basis's Analyst tokens at Haiku rates (exactly 1/3
> of Sonnet's, both input and output, per `configs/pricing.yaml`) and
> scaling ×8 as a sanity check projects ≈$0.25 against the real $0.2104 —
> close, but built on the same linear-scaling assumption this run's own
> Moderator/Persona counts just showed doesn't hold; not a substitute for
> the measurement, reported in the README alongside it for exactly that
> reason.
>
> **This study's findings enter no validity claim, and must not be mistaken
> for a third configuration alongside A and B — stated here so a later
> session can't make that mistake.** Every agent here ran on
> `claude-haiku-4-5`, including the Analyst — the same model Deviation 20/21
> already measured as producing zero `blocker` findings on this artefact and
> reporting *something* for nearly every persona regardless of artefact
> quality. This run measures panel size and cost only. Its `Finding` rows
> are not counted toward, compared against, or cited by discriminative
> validity, calibration, acquiescence, position bias, or any other §M6
> check.
>
> **README updated:** the Cost section now carries both measurements
> side by side, each labelled with its own model mix and study id, the
> repriced-Haiku sanity-check reasoning above, and the no-validity-claim
> caveat above, verbatim, not summarised. The Claim-trace table's single
> "40-persona study cost (extrapolation)" row is split in two: the
> original Config-A extrapolation stays **Unverified**, and a new row for
> this real all-Haiku run reads **Measured**, citing study 146.
> `tests/test_docs_claims.py` has nothing hard-coding the old extrapolation
> wording (checked before editing), so no test needed updating for the
> wording change itself — the file's existing existence/link checks cover
> the new `configs/study.40.yaml` reference the same way they cover every
> other path named in `README.md`.

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

> **M8 note:** filled below from real output where real output exists.
> `[40]` is explicitly **not** filled — no 40-persona study has ever been run
> (largest recorded: 5 personas, PROJECT_SPEC.md §M8's own cost table). The
> literal instruction ("don't estimate") makes `[40]` unfillable without
> running one; recorded here as a deviation rather than silently estimated.
> **Filled in a later session, from a real 40-persona run — see Deviation 22
> for the numbers and, importantly, for what this run does *not* license
> claiming.**

- Built a multi-agent research harness that runs panels of 40 LLM-simulated
  users against product artefacts, with role-isolated moderator/persona/
  analyst agents to prevent hypothesis leakage into responses.
- Designed a provider-agnostic LLM layer with record/replay cassettes, per-call
  cost accounting and budget kill-switches; full test suite runs offline in
  [~83]s (325 tests, `.\make.ps1 test`) with zero API spend.
- Built a validity harness measuring reproducibility, discriminative validity,
  acquiescence bias and known-defect detection rate ([1/3]), and documented the
  conditions under which synthetic panels are and are not informative.
- Implemented resumable async orchestration with concurrency limits and
  exponential backoff, recovering [20]-run studies from mid-flight interruption
  without duplicate work (§M4's own literal acceptance criterion:
  `tests/test_m4_acceptance.py::test_kill_at_50_percent_and_resume_completes_without_duplicate_runs`).
