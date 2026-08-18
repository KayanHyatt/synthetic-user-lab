"""Generate the Mermaid ER diagram for docs/architecture.md from the live ORM metadata.

The diagram in `docs/architecture.md` is never hand-drawn: it is introspected
from `sul.models.Base.metadata` and written back between two marker comments,
so it cannot drift from the actual schema. Regenerate with:

    uv run python -m sul.erd

`tests/test_erd.py` re-renders and compares against the file on disk, so a
schema change with no matching regeneration fails CI rather than silently
going stale.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from sul.models import Base

BEGIN_MARKER = "<!-- BEGIN GENERATED ER DIAGRAM -->"
END_MARKER = "<!-- END GENERATED ER DIAGRAM -->"

_DEFAULT_TEMPLATE = """# Architecture

## Entity-relationship diagram

{block}

## Persona isolation boundary

`Persona` rows never carry the research goal, other personas, or prior
findings — that is enforced structurally, not just by prompt wording:

- `sul.schemas.isolation.PersonaContext` is the only object ever assembled
  into a persona agent's input. It is built from a persona's own card text,
  the artefact under test, and that persona's own prior moderator turns —
  nothing else reaches it.
- `Persona.panel` and `Panel.study` are mapped `lazy="raise"`. Any code path
  that accidentally tries to walk from a `Persona` up to its `Study` (and
  from there, `Study.research_goal`) raises immediately instead of silently
  lazy-loading. Legitimate traversals (the runner, the report renderer) must
  use an explicit `selectinload`/`joinedload`, which keeps every crossing of
  the boundary deliberate and greppable.
- `ModelCall.agent` and `Turn.role` use two different enums
  (`sul.enums.AgentRole` vs `sul.enums.TurnRole`): the Analyst can make model
  calls, but never writes a transcript turn, since it never talks to a
  persona.
"""


def _sanitize_type(column: sa.Column[object]) -> str:
    """Mermaid attribute types cannot contain parentheses or spaces."""
    return str(column.type).split("(")[0].replace(" ", "")


def _column_flags(column: sa.Column[object]) -> list[str]:
    flags = []
    if column.primary_key:
        flags.append("PK")
    if column.foreign_keys:
        flags.append("FK")
    if column.unique:
        flags.append("UK")
    return flags


def render_mermaid_er(metadata: sa.MetaData) -> str:
    """Render every table and foreign key in `metadata` as a Mermaid `erDiagram`."""
    tables = sorted(metadata.tables.values(), key=lambda t: t.name)
    lines = ["erDiagram"]

    for table in tables:
        entity = table.name.upper()
        lines.append(f"    {entity} {{")
        for column in table.columns:
            flag_suffix = (
                " " + " ".join(_column_flags(column)) if _column_flags(column) else ""
            )
            lines.append(f"        {_sanitize_type(column)} {column.name}{flag_suffix}")
        lines.append("    }")

    for table in tables:
        for fk in sorted(
            table.foreign_keys, key=lambda f: (f.column.table.name, f.parent.name)
        ):
            parent = fk.column.table.name.upper()
            child = table.name.upper()
            cardinality = "|o" if fk.parent.nullable else "||"
            lines.append(
                f'    {parent} {cardinality}--o{{ {child} : "{fk.parent.name}"'
            )

    return "\n".join(lines) + "\n"


def write_architecture_doc(path: Path) -> str:
    """(Re)generate the diagram block inside `path`, preserving surrounding prose.

    If `path` does not exist yet, a default document (including the diagram
    block) is created. If it exists, only the text between `BEGIN_MARKER` and
    `END_MARKER` is replaced.
    """
    diagram = render_mermaid_er(Base.metadata)
    block = f"{BEGIN_MARKER}\n\n```mermaid\n{diagram}```\n\n{END_MARKER}"

    if path.exists():
        text = path.read_text(encoding="utf-8")
        if BEGIN_MARKER not in text or END_MARKER not in text:
            raise ValueError(f"{path} exists but is missing the ER diagram markers")
        pre, _, rest = text.partition(BEGIN_MARKER)
        _, _, post = rest.partition(END_MARKER)
        new_text = pre + block + post
    else:
        new_text = _DEFAULT_TEMPLATE.format(block=block)

    path.write_text(new_text, encoding="utf-8")
    return new_text


def _architecture_doc_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "architecture.md"


if __name__ == "__main__":
    doc_path = _architecture_doc_path()
    write_architecture_doc(doc_path)
    print(f"Wrote {doc_path}")
