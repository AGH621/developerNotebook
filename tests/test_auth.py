"""Session auth, registration, and password hashing."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import hash_password, verify_password
from app.models import User

def test_hash_and_verify_round_trip():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) is True
    assert verify_password("wrong", h) is False


def test_register_creates_user_and_redirects_welcome(client: TestClient, test_db: Session):
    r = client.post(
        "/register",
        data={"username": "newbie", "password": "pw-newbie-99"},
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/welcome"
    row = test_db.scalars(select(User).where(User.username == "newbie")).first()
    assert row is not None
    assert verify_password("pw-newbie-99", row.password_hash)


def test_register_duplicate_conflict(client: TestClient, test_db: Session):
    client.post("/register", data={"username": "twice", "password": "a1"})
    r = client.post("/register", data={"username": "twice", "password": "b2"})
    assert r.status_code == 409


def test_login_success_sets_cookie(client: TestClient, test_db: Session):
    client.post("/register", data={"username": "loginok", "password": "secret99"})
    r = client.post("/login", data={"username": "loginok", "password": "secret99"})
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    assert "session" in r.cookies


def test_login_invalid_credentials(client: TestClient, test_db: Session):
    client.post("/register", data={"username": "onlyme", "password": "right"})
    r = client.post("/login", data={"username": "onlyme", "password": "wrong"})
    assert r.status_code == 401


def test_logout_clears_session(client: TestClient, test_db: Session):
    client.post("/register", data={"username": "lg", "password": "p"})
    client.post("/login", data={"username": "lg", "password": "p"})
    assert "session" in client.cookies
    r = client.post("/logout")
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"
    assert client.cookies.get("session") in (None, "")


def test_home_redirects_when_unauthenticated(client: TestClient):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_topic_page_redirects_when_unauthenticated(client: TestClient):
    r = client.get("/topic/git")
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_seed_topics_redirects_when_unauthenticated(client: TestClient):
    r = client.get("/seed-topics")
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


@pytest.fixture
def _registered(client: TestClient):
    client.post(
        "/register",
        data={"username": "slugowner", "password": "pw"},
    )
    client.post("/login", data={"username": "slugowner", "password": "pw"})
    client.post("/topics", data={"name": "Git"})
    return client


def test_authenticated_topic_slug_accessible(_registered: TestClient, test_db: Session):
    from sqlalchemy import select

    from app.models import Topic

    slug = test_db.scalars(select(Topic.slug).where(Topic.name == "Git")).one()
    r = _registered.get(f"/topic/{slug}", follow_redirects=False)
    assert r.status_code == 200
    assert b"Git" in r.content
