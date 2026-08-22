"""The M7 dashboard: FastAPI + Jinja/HTMX, strictly read-only.

No module under `sul.web` imports `sul.runner.orchestrator.run_study`,
`sul.providers.client.ModelClient`, or any concrete provider adapter
(`tests/test_agent_module_hygiene.py`'s AST hygiene check is extended to
this package) -- the dashboard has no code path that can dispatch an LLM
call, which is what makes an unauthenticated, published port defensible:
there is no spend endpoint behind it (PROJECT_SPEC.md §M7 says "Read-only is
fine"; this package takes the stronger reading deliberately).
"""

from __future__ import annotations
