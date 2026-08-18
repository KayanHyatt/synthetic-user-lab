"""Deterministic hashing used for reproducibility and content-addressing.

`config_hash` is what M6's reproducibility claims lean on: if two studies hash
the same, the runner promises they were configured identically, including the
research goal (a study whose only difference is its research question is a
different study, and must hash differently).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def config_hash(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-serialisable config mapping into a stable, order-independent digest.

    Uses `sort_keys=True` so key order in the source mapping never affects the
    result, and a compact separator so incidental whitespace changes don't
    either.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_hash(body: str) -> str:
    """Hash raw content (an artefact body, a prompt) into a sha256 hex digest."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
