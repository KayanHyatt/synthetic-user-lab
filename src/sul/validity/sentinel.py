"""The NOT_MEASURED_OFFLINE sentinel (PROJECT_SPEC.md §M6 implementation
note): four of the five checks synthesize their inputs through `FakeProvider`,
which draws `AnalystFinding.category` uniformly at random
(`sul.providers.fake._synthesize`'s `enum.Enum` branch) and
`AnalystFinding.summary` as random letters, both keyed on the full prompt hash
-- blind to artefact content, question framing, and option position alike.
Any number these checks produced offline would be sampling noise wearing the
shape of a result, not evidence about the panel. See PROJECT_SPEC.md's M6
implementation note for the full argument.

`MeasurementStatus.NOT_MEASURED_OFFLINE` is a value on the model, not an
`Optional` field silently left `None` -- `None` and `0.0` both look like
finished measurements to a reader skimming a table; a distinct enum member
does not, and every renderer branches on it explicitly (see
`sul.validity.report`).
"""

from __future__ import annotations

import enum


class MeasurementStatus(enum.StrEnum):
    """Whether a validity metric was actually measured, or could not be."""

    MEASURED = "measured"
    NOT_MEASURED_OFFLINE = "not_measured_offline"


NOT_MEASURED_OFFLINE_REASON = (
    "FakeProvider synthesizes structured output (category, summary, "
    "agreement, choice) as a uniform-random function of the full prompt "
    "hash -- blind to artefact content, question framing, and option "
    "position. This check requires a real provider (a cassette-backed one "
    "is sufficient and stays offline); measuring it against FakeProvider "
    "would report sampling noise as if it were a result."
)

__all__ = ["NOT_MEASURED_OFFLINE_REASON", "MeasurementStatus"]
