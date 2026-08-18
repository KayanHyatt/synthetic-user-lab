"""The ER diagram in docs/architecture.md is generated, not hand-drawn.

If this test fails, the schema changed and nobody re-ran
`uv run python -m sul.erd`.
"""

from __future__ import annotations

from pathlib import Path

from sul.erd import BEGIN_MARKER, END_MARKER, render_mermaid_er
from sul.models import Base

ARCHITECTURE_DOC = Path(__file__).resolve().parents[1] / "docs" / "architecture.md"


def test_architecture_doc_diagram_matches_generated_output() -> None:
    assert ARCHITECTURE_DOC.exists(), "docs/architecture.md is missing"
    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")

    assert BEGIN_MARKER in text and END_MARKER in text
    _, _, rest = text.partition(BEGIN_MARKER)
    committed_block, _, _ = rest.partition(END_MARKER)

    fresh = render_mermaid_er(Base.metadata)
    expected_block = f"\n\n```mermaid\n{fresh}```\n\n"

    assert committed_block == expected_block, (
        "docs/architecture.md's ER diagram is stale — "
        "run `uv run python -m sul.erd` and commit the result"
    )


def test_every_table_appears_in_the_diagram() -> None:
    diagram = render_mermaid_er(Base.metadata)
    for table in Base.metadata.tables.values():
        assert table.name.upper() in diagram


def test_every_foreign_key_appears_in_the_diagram() -> None:
    diagram = render_mermaid_er(Base.metadata)
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert f'"{fk.parent.name}"' in diagram
