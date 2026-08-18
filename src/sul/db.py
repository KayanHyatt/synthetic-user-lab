"""Engine, session factory and schema creation.

SQLite does not enforce foreign keys by default; without the `PRAGMA
foreign_keys=ON` connect listener below, every FK and cascade test in
`tests/test_models.py` would be exercising a no-op.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sul.models import Base


def make_engine(database_url: str, **kwargs: object) -> Engine:
    """Create an engine with SQLite foreign-key enforcement turned on."""
    engine = sa.create_engine(database_url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_all(engine: Engine) -> None:
    """Create every table declared on `Base.metadata`."""
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a `sessionmaker` bound to `engine`."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """Yield a session, committing on success and rolling back on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
