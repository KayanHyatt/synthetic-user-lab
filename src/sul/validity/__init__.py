"""The M6 validity harness (PROJECT_SPEC.md §M6): five offline checks over a
panel run through `sul.runner.orchestrator.run_study`, written to
`docs/validity_report.md`, plus `docs/limitations.md`.

Every check here takes its `LLMProvider` as a parameter (`sul.validity.harness
.run_validity_harness`) -- the same shape `run_study`/`ModelClient` already
take. `make validate` / `sul validate` always construct `FakeProvider`; there
is no flag that lets that entrypoint construct anything else. A cassette-backed
provider is only ever constructed directly by a test or a dedicated recording
script, never through the `sul validate` code path -- see
`sul.validity.sentinel` for why that separation has to be structural, not a
convention.
"""

from __future__ import annotations
