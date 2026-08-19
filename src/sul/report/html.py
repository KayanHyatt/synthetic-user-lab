"""Render a `ReportModel` to a single self-contained HTML file
(PROJECT_SPEC.md §M5).

**Escaping.** The Jinja environment here has `autoescape=True` -- every
`{{ }}` interpolation is HTML-entity-escaped automatically, which is the
correct and sufficient defence for HTML (unlike Markdown, there is exactly
one escaping mechanism, and Jinja already implements it correctly).
`Turn.content` is rendered inside `<pre>`, which preserves whitespace and
newlines literally; autoescaping still runs on its contents, so `<`, `&`,
`"` and `'` inside a quote render as literal characters, never as markup.

**No network fetch.** All CSS is inlined in `<style>`; there is no
`<link>`, no `<script src=...>`, no `@import`, no webfont. The socket guard
already in this repo's test suite would catch an external fetch at test
time, but by then the page would already be built wrong -- this is enforced
at template-authoring time, not discovered by the guard.
"""

from __future__ import annotations

import jinja2

from sul.report.model import SIMULATED_PANEL_CAVEAT, ReportModel

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.report", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=True,
)


def render_html(report: ReportModel) -> str:
    template = _env.get_template("report.html.j2")
    return template.render(report=report, caveat=SIMULATED_PANEL_CAVEAT)


__all__ = ["render_html"]
