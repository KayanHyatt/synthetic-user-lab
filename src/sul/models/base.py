"""Declarative base shared by every ORM model.

A naming convention gives every constraint (not just primary keys) a
predictable, generated name. Without it SQLite/SQLAlchemy leave unique and
check constraints anonymous, which makes it impossible for a test to assert
"this specific constraint fired" from an `IntegrityError` message.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all `sul` ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
