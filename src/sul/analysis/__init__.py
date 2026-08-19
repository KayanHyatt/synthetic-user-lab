"""Findings analysis: clustering and ranking, both LLM-free (PROJECT_SPEC.md
§M5). Neither module here ever imports `sul.providers` or `sul.runner` — this
package makes no model call, derives no seed, and touches no budget.
"""

from __future__ import annotations
