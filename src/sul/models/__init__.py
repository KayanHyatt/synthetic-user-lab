"""SQLAlchemy ORM models.

Every model is imported here so that a single `import sul.models` (or `from
sul.models import Base`) fully populates `Base.metadata` and the mapper
registry. `sul.erd` and `sul.db.create_all` both depend on this — they only
ever import `sul.models`, never the individual submodules.
"""

from __future__ import annotations

from sul.models.base import Base
from sul.models.finding import Finding
from sul.models.panel import Panel, Persona
from sul.models.run import Run, Turn
from sul.models.study import Artefact, Scenario, Study
from sul.models.telemetry import ModelCall

__all__ = [
    "Artefact",
    "Base",
    "Finding",
    "ModelCall",
    "Panel",
    "Persona",
    "Run",
    "Scenario",
    "Study",
    "Turn",
]
