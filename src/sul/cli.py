"""Typer CLI.

Only `sul cost <study_id>` lands in M2: the rest of the CLI (`personas
sample`, `run`, `report`, `validate`) is M7's scope, but M2's own
acceptance criterion names this one command explicitly (PROJECT_SPEC.md
§M2: "Cost for a demo run is queryable via `sul cost <study_id>`.").
"""

from __future__ import annotations

import typer
from sqlalchemy import func, select

from sul.config import get_settings
from sul.db import make_engine, make_session_factory
from sul.models import ModelCall, Run, Study

app = typer.Typer(help="Synthetic User Lab CLI.")


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


if __name__ == "__main__":
    app()
