"""Render a `ReportModel` to Markdown (PROJECT_SPEC.md §M5).

**Escaping.** `Turn.content` is model output landing inside a structured text
format; nothing about it is safe to interpolate raw. Rather than
backslash-escaping every CommonMark-significant character (`#`, `>`, `|`,
backticks, ...) -- fragile, and easy to miss one -- every quote is wrapped in
a fenced code block whose backtick fence is chosen longer than the longest
run of backticks already present in the quote (`_fence`). Inside a fenced
code block, CommonMark treats the enclosed text as literal until the matching
closing fence: no character inside it is ever reinterpreted as heading,
blockquote, table-row or emphasis syntax, and no per-character escaping is
needed at all. `tests/test_report_rendering.py` proves this against a fixture
built specifically to break naive escaping (`<`, `&`, `|`, `#`, backticks,
an embedded newline).

Long quotes are kept whole here -- Markdown has no equivalent of HTML's
`<details>` collapse, and eliding a quote is not this renderer's decision to
make (PROJECT_SPEC.md's M5 plan: "an excerpt is a place for meaning to
change, and the model must not be the one picking it" -- neither is the
renderer).
"""

from __future__ import annotations

import jinja2

from sul.report.model import SIMULATED_PANEL_CAVEAT, ReportModel


def _fence(text: str) -> str:
    longest_run = 0
    current_run = 0
    for ch in text:
        if ch == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    marker = "`" * max(3, longest_run + 1)
    return f"{marker}\n{text}\n{marker}"


_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.report", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)
_env.filters["fence"] = _fence


def render_markdown(report: ReportModel) -> str:
    template = _env.get_template("report.md.j2")
    return template.render(report=report, caveat=SIMULATED_PANEL_CAVEAT)


__all__ = ["render_markdown"]
