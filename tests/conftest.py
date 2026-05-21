"""Pytest fixtures: in-memory DB, Starlette TestClient (HTTPX-based), auth helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import app.models  # noqa: F401 — register ORM models on Base.metadata
from app.auth import hash_password
from app.database import Base, apply_sqlite_user_column_migrations, get_db
from app.indexing import ensure_fts_table
from app.main import create_app
from app.models import Invitation, User
from app.settings import ensure_app_settings, invalidate_settings_cache

TEST_USERNAME = "testuser"
TEST_PASSWORD = "test-pass-please-123"
TEST_INVITE_CODE = "pytest-invite-token"


@pytest.fixture
def test_db() -> Session:
    """Fresh in-memory SQLite session per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    apply_sqlite_user_column_migrations(engine)
    ensure_fts_table(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    ensure_app_settings(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(test_db: Session):
    """Sync HTTP client driving the ASGI app with ``get_db`` bound to the test session."""
    application = create_app(enable_lifespan=False)

    def _override_get_db():
        yield test_db

    application.dependency_overrides[get_db] = _override_get_db
    with TestClient(application, base_url="http://test", follow_redirects=False) as c:
        _orig_request = c.request

        def _request(method: str, url: str, **kwargs):
            headers = kwargs.pop("headers", None)
            if str(method).upper() in ("POST", "PUT", "PATCH", "DELETE"):
                tok = c.cookies.get("csrftoken")
                if tok:
                    hdrs = dict(headers or {})
                    hdrs.setdefault("x-csrftoken", tok)
                    headers = hdrs
            return _orig_request(method, url, headers=headers, **kwargs)

        c.request = _request  # type: ignore[method-assign]
        yield c
    application.dependency_overrides.clear()


@pytest.fixture
def register_invite(test_db: Session) -> str:
    """Unused invitation row usable for POST ``/register`` in tests."""
    inviter = User(
        username="_pytest_inviter",
        password_hash=hash_password("_unused_inviter_pw_"),
        is_admin=True,
        is_suspended=False,
    )
    test_db.add(inviter)
    test_db.flush()
    test_db.add(Invitation(code=TEST_INVITE_CODE, created_by=inviter.id))
    test_db.commit()
    return TEST_INVITE_CODE


@pytest.fixture
def authenticated_client(client: TestClient, register_invite: str):
    """Client with session cookie after registering a dedicated test user."""
    r = client.post(
        "/register",
        data={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
            "invite_code": register_invite,
        },
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/welcome"
    assert "session" in client.cookies
    return client


@pytest.fixture
def starter_catalog(test_db: Session) -> None:
    """Ensure ``StarterTopic`` / ``StarterSection`` / ``StarterEntry`` rows exist (from bundled data)."""
    from app.bootstrap import seed_starter_catalog_if_empty
    from app.seed_data import STARTER_DATA

    seed_starter_catalog_if_empty(test_db, STARTER_DATA)
    test_db.commit()


@pytest.fixture
def seeded_client(
    authenticated_client: TestClient,
    test_db: Session,
    starter_catalog: None,
):
    """Authenticated client whose user has starter notebook data."""
    from sqlalchemy import select

    from app.models import User
    from app.services.seed import populate_starter_data

    user = test_db.scalars(select(User).where(User.username == TEST_USERNAME)).one()
    populate_starter_data(test_db, user.id)
    test_db.commit()
    return authenticated_client


@pytest.fixture(autouse=True)
def _test_env_security(monkeypatch: pytest.MonkeyPatch):
    """Stable signing secret and HTTP-friendly cookies for Starlette TestClient."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-pytest-only")
    monkeypatch.setenv("SECURE_COOKIES", "false")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    invalidate_settings_cache()
