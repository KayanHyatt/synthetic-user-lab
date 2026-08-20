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

`MeasurementStatus.PARTIALLY_MEASURED` (PROJECT_SPEC.md §M6 Deviation 11)
exists for the same reason, one level down: once the probe path
(`sul.validity.acquiescence`, `.position`) gains per-subject containment, a
section can finish with *some* subjects contributing and others dropped
after a transient failure. A rate computed only over the survivors is not
wrong, but rendering it identically to a full-panel `MEASURED` rate would
hide that the denominator shrank -- the same "looks finished to a skimming
reader" failure this module already argues against for `None`/`0.0`.

A section resolves to `PARTIALLY_MEASURED` whenever `subjects_measured <
subjects_attempted` and provider dispatch actually happened at all --
including the zero-survivor case (`subjects_measured == 0`), where every
rate field stays `None` rather than resolving to a confident `0.0` over an
empty panel. Zero survivors is deliberately not folded into
`NOT_MEASURED_OFFLINE`: that member's own rendered label ("NOT MEASURED
OFFLINE") and reason text are specifically about `FakeProvider`'s
content-blind synthesis (see `NOT_MEASURED_OFFLINE_REASON` below) and would
misdescribe a real-provider section that dispatched real calls and simply
lost every subject to failures. `sul.validity.harness` is the one place
that resolves the three-way status, from `subjects_attempted`/
`subjects_measured` alone.
"""

from __future__ import annotations

import enum


class MeasurementStatus(enum.StrEnum):
    """Whether a validity metric was actually measured, or could not be."""

    MEASURED = "measured"
    PARTIALLY_MEASURED = "partially_measured"
    NOT_MEASURED_OFFLINE = "not_measured_offline"


NOT_MEASURED_OFFLINE_REASON = (
    "FakeProvider synthesizes structured output (category, summary, "
    "agreement, choice) as a uniform-random function of the full prompt "
    "hash -- blind to artefact content, question framing, and option "
    "position. This check requires a real provider (a cassette-backed one "
    "is sufficient and stays offline); measuring it against FakeProvider "
    "would report sampling noise as if it were a result."
)


def partially_measured_reason(*, attempted: int, measured: int) -> str:
    """A per-section reason string naming the actual denominator, not just
    "some subjects failed" -- see `sul.validity.acquiescence
    .AcquiescenceResult.failures` / `sul.validity.position
    .PositionBiasResult.failures` for the per-subject detail this
    summarises.
    """
    return (
        f"{measured} of {attempted} subjects completed every probe call for "
        "this section; the rest failed mid-probe (a transient provider "
        "error or a structured-output parse failure that survived the one "
        "bounded repair turn) and were dropped from every sink for this "
        "section, not just the framing/ordering that failed -- see the "
        "per-subject failure detail recorded alongside this result."
    )


__all__ = [
    "NOT_MEASURED_OFFLINE_REASON",
    "MeasurementStatus",
    "partially_measured_reason",
]
