"""SQLite column migrations for legacy databases without Alembic."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register ORM models on Base.metadata
from app.auth import hash_password
from app.database import Base, apply_sqlite_user_column_migrations
from app.models import User


def test_apply_sqlite_user_column_migrations_adds_missing_columns():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                "username VARCHAR(150) NOT NULL UNIQUE, "
                "password_hash VARCHAR(255) NOT NULL"
                ")",
            ),
        )

    apply_sqlite_user_column_migrations(engine)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    assert "is_admin" in cols
    assert "is_suspended" in cols
    assert "session_version" in cols
    assert "failed_login_count" in cols
    assert "locked_until" in cols
    assert "is_guest" in cols

    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        legacy = User(username="legacy", password_hash=hash_password("x"))
        db.add(legacy)
        db.commit()
        merged = db.get(User, legacy.id)
        assert merged is not None
        assert merged.is_admin is False
        assert merged.is_suspended is False
        assert merged.failed_login_count == 0
        assert merged.locked_until is None
    finally:
        db.close()


def test_apply_sqlite_user_column_migrations_is_idempotent():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    apply_sqlite_user_column_migrations(engine)
    apply_sqlite_user_column_migrations(engine)

    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        db.add(User(username="u", password_hash=hash_password("p")))
        db.commit()
        u = db.query(User).filter_by(username="u").one()
        assert u.is_admin is False
        assert u.is_suspended is False
    finally:
        db.close()
