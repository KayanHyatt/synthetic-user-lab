"""The M4 orchestrator: an async runner over the persona x scenario grid.

`sul.runner.orchestrator.run_study` is the only public entry point. Nothing
under `sul.runner` or `sul.agents` imports a concrete provider adapter --
every call is dispatched through an injected `sul.providers.client.ModelClient`
(see the M4 carry-forward on provider injection, PROJECT_SPEC.md §M4).
"""

from __future__ import annotations
