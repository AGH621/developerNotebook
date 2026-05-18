"""Session auth, registration, and password hashing."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import hash_password, validate_password, verify_password
from app.models import Invitation, User


def test_hash_and_verify_round_trip():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h) is True
    assert verify_password("wrong", h) is False


def test_validate_password_requires_minimum_length():
    assert validate_password("short") is not None
    assert validate_password("longenough") is None


def test_register_get_without_invite_shows_notice(client: TestClient):
    r = client.get("/register", follow_redirects=False)
    assert r.status_code == 200
    assert b"invitation" in r.content.lower()


def test_register_get_with_valid_invite(client: TestClient, register_invite: str):
    r = client.get(f"/register?code={register_invite}", follow_redirects=False)
    assert r.status_code == 200
    assert 'name="invite_code"' in r.text


def test_register_post_rejects_unknown_invite(client: TestClient, test_db: Session):
    r = client.post(
        "/register",
        data={"username": "ghost", "password": "pw1-longer", "invite_code": "not-a-real-code"},
        follow_redirects=False,
    )
    assert r.status_code == 409
    assert test_db.scalars(select(User).where(User.username == "ghost")).first() is None


def test_register_rejects_short_password(client: TestClient, test_db: Session, register_invite: str):
    r = client.post(
        "/register",
        data={
            "username": "shortpw",
            "password": "seven77",
            "invite_code": register_invite,
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert test_db.scalars(select(User).where(User.username == "shortpw")).first() is None


def test_register_creates_user_and_redirects_welcome(client: TestClient, test_db: Session, register_invite: str):
    r = client.post(
        "/register",
        data={
            "username": "newbie",
            "password": "pw-newbie-99",
            "invite_code": register_invite,
        },
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/welcome"
    row = test_db.scalars(select(User).where(User.username == "newbie")).first()
    assert row is not None
    assert verify_password("pw-newbie-99", row.password_hash)


def test_register_duplicate_conflict(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "twice", "password": "a1-longer", "invite_code": register_invite},
    )
    inviter_id = test_db.scalars(select(User.id).where(User.username == "_pytest_inviter")).one()
    test_db.add(Invitation(code="pytest-invite-token-2", created_by=inviter_id))
    test_db.commit()
    r = client.post(
        "/register",
        data={
            "username": "twice",
            "password": "b2-longer",
            "invite_code": "pytest-invite-token-2",
        },
    )
    assert r.status_code == 409


def test_invite_marked_used_after_registration(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "redeemer", "password": "pw-longer", "invite_code": register_invite},
    )
    inv = test_db.scalars(select(Invitation).where(Invitation.code == register_invite)).one()
    assert inv.used_by is not None


def test_login_success_sets_cookie(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "loginok", "password": "ok-secret-99", "invite_code": register_invite},
    )
    r = client.post("/login", data={"username": "loginok", "password": "ok-secret-99"})
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    assert "session" in r.cookies


def test_login_invalid_credentials(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "onlyme", "password": "right-pass", "invite_code": register_invite},
    )
    r = client.post("/login", data={"username": "onlyme", "password": "wrong"})
    assert r.status_code == 401


def test_login_blocked_when_account_suspended(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "suspended-user", "password": "ok-pw-long", "invite_code": register_invite},
    )
    db_user = test_db.scalars(select(User).where(User.username == "suspended-user")).one()
    db_user.is_suspended = True
    test_db.commit()

    r = client.post("/login", data={"username": "suspended-user", "password": "ok-pw-long"})
    assert r.status_code == 403
    assert b"suspended" in r.content.lower()


def test_existing_session_invalidated_when_account_suspended(
    client: TestClient,
    test_db: Session,
    register_invite: str,
):
    client.post(
        "/register",
        data={"username": "susp-cookie", "password": "x-longer", "invite_code": register_invite},
    )
    client.post("/login", data={"username": "susp-cookie", "password": "x-longer"})
    assert client.get("/", follow_redirects=False).status_code == 200
    db_user = test_db.scalars(select(User).where(User.username == "susp-cookie")).one()
    db_user.is_suspended = True
    test_db.commit()
    r_home = client.get("/", follow_redirects=False)
    assert r_home.status_code == 303
    assert r_home.headers.get("location") == "/login"


def test_logout_clears_session(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "lg", "password": "lg-secret-99", "invite_code": register_invite},
    )
    client.post("/login", data={"username": "lg", "password": "lg-secret-99"})
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


def test_admin_ok_requires_admin_role(client: TestClient, test_db: Session, register_invite: str):
    test_db.add(
        User(
            username="adm",
            password_hash=hash_password("adm-secret-9"),
            is_admin=True,
            is_suspended=False,
        ),
    )
    test_db.commit()

    client.post(
        "/register",
        data={"username": "member", "password": "pw-longer", "invite_code": register_invite},
    )
    assert client.get("/admin/ok").status_code == 403

    client.post("/logout")
    client.post("/login", data={"username": "adm", "password": "adm-secret-9"})
    assert client.get("/admin/ok").status_code == 200


def test_admin_ok_redirects_when_unauthenticated(client: TestClient):
    r = client.get("/admin/ok", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


@pytest.fixture
def _registered(client: TestClient, register_invite: str):
    client.post(
        "/register",
        data={"username": "slugowner", "password": "pw-longer", "invite_code": register_invite},
    )
    client.post("/login", data={"username": "slugowner", "password": "pw-longer"})
    client.post("/topics", data={"name": "Git"})
    return client


def test_authenticated_topic_slug_accessible(_registered: TestClient, test_db: Session):
    from app.models import Topic

    slug = test_db.scalars(select(Topic.slug).where(Topic.name == "Git")).one()
    r = _registered.get(f"/topic/{slug}", follow_redirects=False)
    assert r.status_code == 200
    assert b"Git" in r.content
