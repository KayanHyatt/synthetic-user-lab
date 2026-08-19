"""The current commit sha, for `Study.git_sha`'s provenance column.

Reads local git state via a subprocess (`git rev-parse HEAD`), never the
network -- unaffected by the offline socket guard in
`tests/conftest.py::_block_network`. Falls back to 40 zeros if git is
unavailable or the working tree isn't a git repository at all, since
`Study.git_sha` is `NOT NULL` and this is provenance metadata, not something
correctness depends on.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

_FALLBACK_SHA = "0" * 40


@lru_cache(maxsize=1)
def current_git_sha() -> str:
    """The current commit's full sha, or `_FALLBACK_SHA` if it can't be read."""
    repo_root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _FALLBACK_SHA
    if result.returncode != 0:
        return _FALLBACK_SHA
    sha = result.stdout.strip()
    return sha if len(sha) == 40 else _FALLBACK_SHA


__all__ = ["current_git_sha"]
