"""The dashboard's one Jinja environment.

`autoescape=True`, exactly M5's `sul.report.html` configuration
(`jinja2.Environment(..., autoescape=True)`) -- hand-built rather than
FastAPI's `Jinja2Templates` wrapper, whose default `select_autoescape` turns
autoescaping on or off *per template name extension*. This project's
templates all end `.html.j2`, so `select_autoescape`'s default extension
list (`.html`, `.htm`, `.xml`) would silently miss every one of them and
autoescaping would never fire -- exactly the kind of "a partial re-declares
its own escaping configuration" gap PROJECT_SPEC.md's §M7 security review
asks about. Building the `Environment` by hand sidesteps the question:
there is one autoescape setting, declared once, applying to every template
by construction, not by matching a filename pattern.

`ChoiceLoader` over both `sul.web`'s own templates and `sul.report`'s means
the dashboard's report view can `{% include "_clusters.html.j2" %}` the
exact fragment `sul.report.html` renders (PROJECT_SPEC.md §M7 deviation:
"the dashboard shares that fragment rather than being a third renderer") --
one escaping configuration, one markup shape, reused, not re-authored.

Every route (full page) and every partial (`sul.web.app`'s
`/partials/...` routes) render through `render_template` below, the same
function, so "does the partial path share the escaping configuration of the
full-page path" has one, structurally enforced answer: yes, they are the
same `jinja2.Environment` object (`tests/test_web_escaping.py` asserts this
by identity, not just by equal settings).
"""

from __future__ import annotations

import jinja2

from sul.report.model import SIMULATED_PANEL_CAVEAT
from sul.web.static_assets import HTMX_FILENAME

env = jinja2.Environment(
    loader=jinja2.ChoiceLoader(
        [
            jinja2.PackageLoader("sul.web", "templates"),
            jinja2.PackageLoader("sul.report", "templates"),
        ]
    ),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=True,
)


def render_template(name: str, **context: object) -> str:
    """Render `name` with `caveat` always in context -- every page and every
    partial carries `SIMULATED_PANEL_CAVEAT` whether or not its own template
    body happens to reference it, so a template author cannot forget to pass
    it and a swap cannot leave it out (PROJECT_SPEC.md §M7: "every dashboard
    page, the demo output... needs [the standing caveat]").
    """
    template = env.get_template(name)
    return template.render(
        caveat=SIMULATED_PANEL_CAVEAT, htmx_filename=HTMX_FILENAME, **context
    )


__all__ = ["env", "render_template"]
