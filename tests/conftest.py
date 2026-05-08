"""Pytest fixtures: in-memory DB, Starlette TestClient (HTTPX-based), auth helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import app.models  # noqa: F401 — register ORM models on Base.metadata
from app.database import Base, get_db
from app.main import create_app

TEST_USERNAME = "testuser"
TEST_PASSWORD = "test-pass-please-123"


@pytest.fixture
def test_db() -> Session:
    """Fresh in-memory SQLite session per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
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
        yield c
    application.dependency_overrides.clear()


@pytest.fixture
def authenticated_client(client: TestClient):
    """Client with session cookie after registering a dedicated test user."""
    r = client.post(
        "/register",
        data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/welcome"
    assert "session" in client.cookies
    return client


@pytest.fixture
def seeded_client(authenticated_client: TestClient, test_db: Session):
    """Authenticated client whose user has starter notebook data."""
    from sqlalchemy import select

    from app.models import User
    from app.services.seed import populate_starter_data

    user = test_db.scalars(select(User).where(User.username == TEST_USERNAME)).one()
    populate_starter_data(test_db, user.id)
    test_db.commit()
    return authenticated_client


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch: pytest.MonkeyPatch):
    """Stable session signing secret for deterministic cookie tests."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-for-pytest-only")
