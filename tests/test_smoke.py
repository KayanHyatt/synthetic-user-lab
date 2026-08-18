"""Smoke test: confirms the package imports and the test suite itself runs.

This exists purely as an M0 guardrail — it gives `pytest` something to collect
and pass before any real domain code lands in M1+.
"""

import sul


def test_package_imports() -> None:
    assert sul.__version__ == "0.1.0"
