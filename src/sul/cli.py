"""Typer CLI.

`sul cost <study_id>` landed in M2 (PROJECT_SPEC.md §M2's own acceptance
criterion). `sul report <study_id>` lands in M5 (§M5: "`sul report
<study_id>` produces a report..."). `sul validate` lands in M6 (§M6:
"`make validate` runs five checks and writes `docs/validity_report.md`"),
following the same precedent -- both land ahead of the rest of the CLI
(`personas sample`, `run`), which remains M7's scope.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import typer
from sqlalchemy import func, select

from sul.analysis.config import ClusteringConfig, load_clustering_config
from sul.config import Settings, get_settings
from sul.db import create_all, make_engine, make_session_factory
from sul.enums import AgentRole
from sul.models import ModelCall, Run, Study
from sul.providers.anthropic import AnthropicProvider
from sul.providers.base import LLMProvider
from sul.providers.cassette import CassetteTransport
from sul.providers.fake import FakeProvider
from sul.report.build import StudyNotFoundError, build_report
from sul.report.html import render_html
from sul.report.markdown import render_markdown
from sul.validity.harness import run_validity_harness
from sul.validity.limitations import render_limitations_markdown
from sul.validity.markdown import render_validity_markdown

app = typer.Typer(help="Synthetic User Lab CLI.")

# The exact model configuration recorded into tests/cassettes/ by
# scripts/record_validity_cassettes.py's "Config A" (PROJECT_SPEC.md §M6
# Deviation 12/13): Persona/Moderator/probes on Haiku, Analyst on Sonnet.
# `_select_validate_provider` below must dispatch on this exact
# configuration whenever cassettes are present -- any drift produces a
# `CassetteMissError`, a hard, visible failure, never a silent live
# dispatch (§M6's own "no test/command ever hits a real API" discipline
# extends to `sul validate`: replay-only, `record=False`, always).
_CASSETTE_CONFIG_MODEL = "claude-haiku-4-5"
_CASSETTE_CONFIG_ANALYST_MODEL = "claude-sonnet-5"


def _select_validate_provider(
    settings: Settings,
) -> tuple[LLMProvider, str, str, dict[AgentRole, str] | None]:
    """Choose `sul validate`'s provider (PROJECT_SPEC.md §M6 Deviation 5,
    amended): a cassette-backed, replay-only `AnthropicProvider` when
    `settings.cassette_dir` holds at least one recorded cassette, else
    `FakeProvider`. Returns exactly one of the two-member allow-list
    `run_validity_harness` itself enforces (§M6 Deviation 7) -- this
    function is the only place that decides which, and it is not
    user-selectable (no flag on this command chooses a provider; see
    `tests/test_cli_validate.py`).
    """
    cassette_dir = settings.cassette_dir
    if cassette_dir.exists() and any(cassette_dir.glob("*.json")):
        transport = CassetteTransport(
            httpx.AsyncHTTPTransport(), cassette_dir, record=False
        )
        # Never actually sent anywhere: record=False means replay-only, and
        # a cassette miss raises CassetteMissError rather than dispatching.
        provider: LLMProvider = AnthropicProvider(
            "sul-validate-replay-only-sentinel-key", transport=transport
        )
        return (
            provider,
            "anthropic",
            _CASSETTE_CONFIG_MODEL,
            {AgentRole.ANALYST: _CASSETTE_CONFIG_ANALYST_MODEL},
        )
    return FakeProvider(), "fake", "fake-1", None


@app.callback()
def main() -> None:
    """Synthetic User Lab CLI.

    A no-op callback: Typer collapses a single-command app so that command's
    name is dropped from the invocation (`sul <study_id>` instead of `sul
    cost <study_id>`) — registering a callback forces it to keep dispatching
    by subcommand name instead, which both matches the spec's literal
    `sul cost <study_id>` and keeps this invocation stable once M7 adds
    `personas sample` / `run` / `report` / `validate` alongside it.
    """


@app.command()
def cost(study_id: int) -> None:
    """Print total spend for STUDY_ID, broken down by provider/model/agent."""
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        study = session.get(Study, study_id)
        if study is None:
            typer.echo(f"No study with id={study_id}")
            raise typer.Exit(code=1)

        total = session.execute(
            select(func.coalesce(func.sum(ModelCall.cost_usd), 0.0))
            .select_from(ModelCall)
            .join(Run, Run.id == ModelCall.run_id)
            .where(Run.study_id == study_id)
        ).scalar_one()

        breakdown = session.execute(
            select(
                ModelCall.provider,
                ModelCall.model,
                ModelCall.agent,
                func.count(ModelCall.id),
                func.coalesce(func.sum(ModelCall.cost_usd), 0.0),
            )
            .select_from(ModelCall)
            .join(Run, Run.id == ModelCall.run_id)
            .where(Run.study_id == study_id)
            .group_by(ModelCall.provider, ModelCall.model, ModelCall.agent)
            .order_by(ModelCall.provider, ModelCall.model, ModelCall.agent)
        ).all()

    typer.echo(f"Study {study_id} ({study.name}): ${total:.4f}")
    for provider, model, agent, count, subtotal in breakdown:
        agent_label = agent.value if hasattr(agent, "value") else agent
        typer.echo(
            f"  {provider}/{model} [{agent_label}]: {count} calls, ${subtotal:.4f}"
        )


@app.command()
def report(
    study_id: int,
    out_dir: Path = typer.Option(
        Path("reports"), "--out-dir", help="Directory to write the report files into."
    ),
    clustering_config_path: Path | None = typer.Option(
        None,
        "--clustering-config",
        help="Path to a ClusteringConfig YAML file. Defaults built into "
        "ClusteringConfig are used if omitted.",
    ),
    include_failed: bool = typer.Option(
        False,
        "--include-failed",
        help="Include findings from FAILED (not just COMPLETED) runs.",
    ),
) -> None:
    """Render a Markdown + HTML report for STUDY_ID to OUT_DIR."""
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    clustering_config = (
        load_clustering_config(clustering_config_path)
        if clustering_config_path is not None
        else ClusteringConfig()
    )

    with session_factory() as session:
        try:
            report_model = build_report(
                session,
                study_id=study_id,
                clustering_config=clustering_config,
                include_failed=include_failed,
            )
        except StudyNotFoundError:
            typer.echo(f"No study with id={study_id}", err=True)
            raise typer.Exit(code=1) from None

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"study_{study_id}_report.md"
    html_path = out_dir / f"study_{study_id}_report.html"
    md_path.write_text(render_markdown(report_model), encoding="utf-8")
    html_path.write_text(render_html(report_model), encoding="utf-8")

    typer.echo(str(md_path))
    typer.echo(str(html_path))


@app.command()
def validate(
    out_dir: Path = typer.Option(
        Path("docs"),
        "--out-dir",
        help="Directory to write validity_report.md and limitations.md into.",
    ),
) -> None:
    """Run the M6 validity harness end-to-end offline and write
    docs/validity_report.md + docs/limitations.md.

    Runs against a cassette-backed, replay-only `AnthropicProvider` when
    `tests/cassettes/` holds recorded traffic, falling back to `FakeProvider`
    when it's empty (PROJECT_SPEC.md §M6 Deviation 5, amended) --
    `_select_validate_provider` is the only place that decides which, and
    there is no flag on this command that picks either one directly or
    points it at anything outside `run_validity_harness`'s own two-member
    allow-list (§M6 Deviation 7; `tests/test_cli_validate.py` checks this
    structurally, against the command's actual `--help` output). Replay is
    the only mode either path ever uses -- "offline" always means "no live
    API call," not "always FakeProvider."
    """
    settings = get_settings()
    engine = make_engine(settings.database_url)
    # Unlike `sul cost`/`sul report`, `sul validate` needs no pre-existing
    # study -- it materialises its own -- so it's the first CLI command that
    # can be the very first thing run against a fresh clone's database.
    create_all(engine)
    session_factory = make_session_factory(engine)

    provider, provider_name, model, model_by_agent = _select_validate_provider(settings)
    report = asyncio.run(
        run_validity_harness(
            session_factory,
            provider=provider,
            provider_name=provider_name,
            model=model,
            model_by_agent=model_by_agent,
        )
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    validity_path = out_dir / "validity_report.md"
    limitations_path = out_dir / "limitations.md"
    validity_path.write_text(render_validity_markdown(report), encoding="utf-8")
    limitations_path.write_text(render_limitations_markdown(report), encoding="utf-8")

    typer.echo(str(validity_path))
    typer.echo(str(limitations_path))


if __name__ == "__main__":
    app()
