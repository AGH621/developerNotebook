"""Session auth, registration, and password hashing."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import _session_serializer, hash_password, validate_password, verify_password
from app.models import AppSettings, Invitation, User
from app.settings import (
    DEFAULT_SESSION_ABSOLUTE_MINUTES,
    DEFAULT_SESSION_IDLE_MINUTES,
    SETTINGS_ROW_ID,
    ensure_app_settings,
    invalidate_settings_cache,
)
from tests.conftest import TEST_PASSWORD, TEST_USERNAME


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


def test_nav_user_menu_links(authenticated_client: TestClient):
    r = authenticated_client.get("/")
    assert r.status_code == 200
    assert b"site-nav__user-menu" in r.content
    assert TEST_USERNAME.encode() in r.content
    assert b'href="/change-password"' in r.content
    assert b'href="/delete-account"' in r.content
    assert b'action="/logout"' in r.content
    assert b"Change password" in r.content
    assert b"Delete account" in r.content
    assert b"Log out" in r.content


def test_nav_user_menu_hides_delete_for_admin(client: TestClient, test_db: Session):
    test_db.add(
        User(
            username="navadmin",
            password_hash=hash_password("navadmin-pw-9"),
            is_admin=True,
            is_suspended=False,
        )
    )
    test_db.commit()
    client.post("/login", data={"username": "navadmin", "password": "navadmin-pw-9"})
    r = client.get("/")
    assert r.status_code == 200
    assert b"site-nav__user-menu" in r.content
    assert b"navadmin" in r.content
    assert b"Delete account" not in r.content
    assert b'href="/delete-account"' not in r.content


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


def test_change_password_requires_auth(client: TestClient):
    r = client.get("/change-password", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_change_password_rejects_wrong_current(authenticated_client: TestClient):
    r = authenticated_client.post(
        "/change-password",
        data={
            "current_password": "wrong",
            "new_password": "new-secret-99",
            "confirm_password": "new-secret-99",
        },
    )
    assert r.status_code == 401
    assert b"incorrect" in r.content.lower()


def test_change_password_success(authenticated_client: TestClient, test_db: Session):
    r = authenticated_client.post(
        "/change-password",
        data={
            "current_password": "test-pass-please-123",
            "new_password": "updated-secret-99",
            "confirm_password": "updated-secret-99",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers.get("location") == "/change-password?ok=1"

    authenticated_client.post("/logout")
    assert (
        authenticated_client.post(
            "/login",
            data={"username": "testuser", "password": "test-pass-please-123"},
        ).status_code
        == 401
    )
    r_login = authenticated_client.post(
        "/login",
        data={"username": "testuser", "password": "updated-secret-99"},
    )
    assert r_login.status_code == 303
    row = test_db.scalars(select(User).where(User.username == "testuser")).one()
    assert verify_password("updated-secret-99", row.password_hash)


def test_delete_account_requires_auth(client: TestClient):
    r = client.get("/delete-account", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_delete_account_removes_user_and_data(
    seeded_client: TestClient,
    test_db: Session,
):
    from sqlalchemy import func

    from app.models import Topic

    user = test_db.scalars(select(User).where(User.username == "testuser")).one()
    topic_count_before = test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id))
    assert topic_count_before and topic_count_before > 0

    r = seeded_client.post(
        "/delete-account",
        data={"password": "test-pass-please-123"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers.get("location", "").startswith("/login?ok=")
    assert test_db.scalars(select(User).where(User.username == "testuser")).first() is None
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == 0


def test_delete_account_blocks_admin(client: TestClient, test_db: Session):
    admin = User(
        username="adminuser",
        password_hash=hash_password("admin-pw-9"),
        is_admin=True,
        is_suspended=False,
    )
    test_db.add(admin)
    test_db.commit()

    client.post("/login", data={"username": "adminuser", "password": "admin-pw-9"})
    r_get = client.get("/delete-account", follow_redirects=False)
    assert r_get.status_code == 303
    assert r_get.headers.get("location") == "/change-password"

    r_post = client.post(
        "/delete-account",
        data={"password": "admin-pw-9"},
        follow_redirects=False,
    )
    assert r_post.status_code == 403
    assert b"administrator accounts cannot be deleted" in r_post.content.lower()
    assert test_db.scalars(select(User).where(User.username == "adminuser")).first() is not None


def _set_session_timeouts(test_db: Session, *, absolute: int, idle: int) -> None:
    settings = test_db.get(AppSettings, SETTINGS_ROW_ID)
    assert settings is not None
    settings.session_absolute_minutes = absolute
    settings.session_idle_minutes = idle
    test_db.commit()
    invalidate_settings_cache()


@contextmanager
def _frozen_time(when: float):
    """Patch wall clock and auth clock (httpx cookie jar uses ``time.time``)."""
    with (
        patch("time.time", return_value=when),
        patch("app.auth.time.time", return_value=when),
    ):
        yield


def _relogin_at(authenticated_client: TestClient, when: float) -> None:
    authenticated_client.post("/logout")
    with _frozen_time(when):
        r = authenticated_client.post(
            "/login",
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
    assert r.status_code == 303


def test_ensure_app_settings_defaults(test_db: Session):
    row = ensure_app_settings(test_db)
    test_db.commit()
    assert row.session_absolute_minutes == DEFAULT_SESSION_ABSOLUTE_MINUTES
    assert row.session_idle_minutes == DEFAULT_SESSION_IDLE_MINUTES


def test_session_absolute_timeout(authenticated_client: TestClient, test_db: Session):
    t0 = 1_700_000_000.0
    _relogin_at(authenticated_client, t0)
    _set_session_timeouts(test_db, absolute=10, idle=100_000)

    with _frozen_time(t0 + 11 * 60):
        r = authenticated_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert "expired" in (r.headers.get("location") or "").lower()


def test_session_idle_timeout(authenticated_client: TestClient, test_db: Session):
    t0 = 1_700_000_000.0
    _set_session_timeouts(test_db, absolute=100_000, idle=10)
    _relogin_at(authenticated_client, t0)

    with _frozen_time(t0 + 11 * 60):
        r = authenticated_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert "expired" in (r.headers.get("location") or "").lower()


def test_session_idle_refresh_extends_session(
    authenticated_client: TestClient,
    test_db: Session,
):
    t0 = 1_700_000_000.0
    _set_session_timeouts(test_db, absolute=100_000, idle=60)
    _relogin_at(authenticated_client, t0)

    with _frozen_time(t0 + 30 * 60):
        r_mid = authenticated_client.get("/", follow_redirects=False)
    assert r_mid.status_code == 200

    with _frozen_time(t0 + 95 * 60):
        r_late = authenticated_client.get("/", follow_redirects=False)
    assert r_late.status_code == 303
    assert "expired" in (r_late.headers.get("location") or "").lower()


def test_legacy_session_cookie_rejected(
    authenticated_client: TestClient,
    test_db: Session,
):
    user = test_db.scalars(select(User).where(User.username == TEST_USERNAME)).one()
    token = _session_serializer().dumps(
        {"user_id": user.id, "session_version": user.session_version},
    )
    authenticated_client.cookies.set("session", token)
    r = authenticated_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"
