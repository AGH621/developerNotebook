"""Database engine, session factory, and FastAPI dependency."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE_URL = f"sqlite:///{_PROJECT_ROOT / 'notebook.db'}"
DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_SQLITE_URL).strip() or _DEFAULT_SQLITE_URL

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for ORM models."""


def apply_sqlite_user_column_migrations(engine: Engine) -> None:
    """Add ``is_admin`` / ``is_suspended`` to ``users`` when missing (legacy DBs).

    The app uses ``create_all`` without Alembic; new installs get columns from
    the ORM. Existing SQLite files need ``ALTER TABLE`` when those fields were
    added later.
    """
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return
    present = {c["name"] for c in inspector.get_columns("users")}
    alters: list[str] = []
    if "is_admin" not in present:
        alters.append(
            "ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0",
        )
    if "is_suspended" not in present:
        alters.append(
            "ALTER TABLE users ADD COLUMN is_suspended BOOLEAN NOT NULL DEFAULT 0",
        )
    if "session_version" not in present:
        alters.append(
            "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0",
        )
    if "failed_login_count" not in present:
        alters.append(
            "ALTER TABLE users ADD COLUMN failed_login_count INTEGER NOT NULL DEFAULT 0",
        )
    if "locked_until" not in present:
        alters.append(
            "ALTER TABLE users ADD COLUMN locked_until DATETIME",
        )
    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))


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
