"""Render a `ValidityReportModel` to `docs/validity_report.md`
(PROJECT_SPEC.md §M6). Mirrors `sul.report.markdown`'s shape (one Jinja
environment, one template, no logic beyond passing the model through) --
there is no escaping hazard here the way there is in `sul.report`: every
value rendered is a number, a boolean, or a string this codebase itself
wrote (a question, a defect description), never raw model/persona output.
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


def render_validity_markdown(report: ValidityReportModel) -> str:
    template = _env.get_template("validity_report.md.j2")
    return template.render(
        report=report,
        MEASURED=MeasurementStatus.MEASURED,
        NOT_MEASURED_OFFLINE=MeasurementStatus.NOT_MEASURED_OFFLINE,
    )


__all__ = ["render_validity_markdown"]
