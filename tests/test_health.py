"""Health check endpoint for load balancers and Fly.io probes."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.database import get_db
from app.main import create_app


def test_health_returns_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.text == "ok"


def test_health_bypasses_trusted_host_in_production(
    monkeypatch: pytest.MonkeyPatch,
    test_db,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOWED_HOSTS", "developer-memory-garden.fly.dev")
    application = create_app(enable_lifespan=False)

    def _override_get_db():
        yield test_db

    application.dependency_overrides[get_db] = _override_get_db
    with TestClient(application, base_url="http://test", follow_redirects=False) as c:
        r = c.get("/health", headers={"Host": "127.0.0.1:8080"})
        assert r.status_code == 200
        assert r.text == "ok"

        r_home = c.get("/", headers={"Host": "127.0.0.1:8080"})
        assert r_home.status_code == 400
        assert b"Invalid host header" in r_home.content
    application.dependency_overrides.clear()
