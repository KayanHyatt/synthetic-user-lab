"""Base class for every Pydantic boundary schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """A Pydantic model buildable from an ORM instance via `.model_validate(orm)`."""

    model_config = ConfigDict(from_attributes=True)
