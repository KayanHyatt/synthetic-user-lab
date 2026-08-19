"""The three role-isolated agents: moderator, persona, analyst.

None of these modules imports `sul.models` (an ORM object crossing into a
persona-bound or analyst-bound function is exactly the leak the isolation
tests exist to catch -- PROJECT_SPEC.md §M4 carry-forward) or a concrete
provider adapter (`sul.providers.{anthropic,openai,gemini,fake}` --
`sul.providers.client.ModelClient` is always injected, never constructed
here). `tests/test_agent_module_hygiene.py` enforces both at the AST level.
"""

from __future__ import annotations
