"""Render `docs/limitations.md` from a `ValidityReportModel` (PROJECT_SPEC.md
§M6: "Write docs/limitations.md from the results"). Prose synthesised from
three offline-measurable weaknesses (`sul.validity.measurements`), never from
the four provider-gated checks -- see the template's own final section for
why those don't count toward the "at least two concrete, measured
weaknesses" acceptance criterion.
"""

from __future__ import annotations

import jinja2

from sul.validity.model import ValidityReportModel
from sul.validity.sentinel import MeasurementStatus

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("sul.validity", "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def render_limitations_markdown(report: ValidityReportModel) -> str:
    template = _env.get_template("limitations.md.j2")
    return template.render(
        report=report,
        MEASURED=MeasurementStatus.MEASURED,
        NOT_MEASURED_OFFLINE=MeasurementStatus.NOT_MEASURED_OFFLINE,
    )


__all__ = ["render_limitations_markdown"]
