"""SQLite database engine, session factory, and FastAPI dependency."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{_PROJECT_ROOT / 'notebook.db'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Provide a request-scoped SQLAlchemy session.

    Yields
    ------
    Session
        Database session; closed after the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
