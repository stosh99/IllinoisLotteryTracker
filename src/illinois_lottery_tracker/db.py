"""Database engine, session factory, and small helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings, get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None) -> Engine:
    """Return a process-wide SQLAlchemy engine, building it on first use."""
    global _engine, _SessionLocal
    if _engine is None:
        settings = settings or get_settings()
        url = settings.require_database_url()
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def _session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    """Context manager that yields a session and commits/rolls back on exit."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables() -> None:
    """Create every table declared on the metadata. Early-development helper."""
    from . import analytics_models, auth_models  # noqa: F401
    from .models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
