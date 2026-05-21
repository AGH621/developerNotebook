"""Guest read-only browsing."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.auth import hash_password
from app.bootstrap import bootstrap_guest_user, ensure_starter_topic_slugs
from app.models import StarterEntry, StarterSection, StarterTopic, User
from app.slug import allocate_starter_topic_slug


@pytest.fixture
def guest_user(test_db):
    """Shared read-only guest account."""
    bootstrap_guest_user(test_db)
    test_db.commit()
    return test_db.scalars(select(User).where(User.is_guest.is_(True))).one()


@pytest.fixture
def guest_client(client: TestClient, guest_user: User) -> TestClient:
    r = client.post("/guest-login")
    assert r.status_code == 303
    assert "session" in client.cookies
    return client


@pytest.fixture
def guest_visible_topic(test_db, starter_catalog: None) -> StarterTopic:
    topic = test_db.scalars(select(StarterTopic)).first()
    assert topic is not None
    ensure_starter_topic_slugs(test_db)
    topic.guest_visible = True
    if not topic.slug:
        topic.slug = allocate_starter_topic_slug(test_db, topic.name, exclude_topic_id=topic.id)
    test_db.commit()
    test_db.refresh(topic)
    return topic


def test_guest_login_shows_home(guest_client: TestClient):
    r = guest_client.get("/")
    assert r.status_code == 200
    assert b"browsing as a guest" in r.content


def test_guest_empty_catalog_message(guest_client: TestClient):
    r = guest_client.get("/")
    assert r.status_code == 200
    assert b"Nothing currently available" in r.content


def test_guest_sees_visible_topic(
    guest_client: TestClient,
    guest_visible_topic: StarterTopic,
):
    r = guest_client.get("/")
    assert r.status_code == 200
    assert guest_visible_topic.name.encode() in r.content
    assert b"Nothing currently available" not in r.content

    detail = guest_client.get(f"/topic/{guest_visible_topic.slug}")
    assert detail.status_code == 200
    assert guest_visible_topic.name.encode() in detail.content


def test_guest_cannot_create_topic(guest_client: TestClient):
    r = guest_client.post("/topics", data={"name": "Sneaky"})
    assert r.status_code == 403


def test_guest_cannot_access_seed_topics(guest_client: TestClient):
    r = guest_client.get("/seed-topics", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_guest_search_scoped_to_visible(
    guest_client: TestClient,
    guest_visible_topic: StarterTopic,
    test_db,
):
    section = test_db.scalars(
        select(StarterSection).where(StarterSection.topic_id == guest_visible_topic.id),
    ).first()
    assert section is not None
    entry = test_db.scalars(
        select(StarterEntry).where(StarterEntry.section_id == section.id),
    ).first()
    assert entry is not None

    r = guest_client.get("/search", params={"q": entry.description[:8]})
    assert r.status_code == 200
    assert guest_visible_topic.name.encode() in r.content


def test_guest_index_includes_visible_entries(
    guest_client: TestClient,
    guest_visible_topic: StarterTopic,
):
    r = guest_client.get("/index")
    assert r.status_code == 200
    assert guest_visible_topic.name.encode() in r.content


def test_login_page_has_browse_as_guest(client: TestClient, guest_user: User):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Browse as guest" in r.content


def test_password_login_rejects_guest_account(client: TestClient, guest_user: User):
    r = client.post(
        "/login",
        data={"username": guest_user.username, "password": "any-password"},
    )
    assert r.status_code == 403
    assert b"Browse as guest" in r.content


def test_admin_can_toggle_guest_visible(
    client: TestClient,
    test_db,
    starter_catalog: None,
):
    from app.models import Invitation

    admin = User(username="_guest_admin_", password_hash=hash_password("admin-pass-123"), is_admin=True)
    test_db.add(admin)
    test_db.flush()
    test_db.add(Invitation(code="guest-toggle-invite", created_by=admin.id))
    topic = test_db.scalars(select(StarterTopic)).first()
    ensure_starter_topic_slugs(test_db)
    test_db.commit()

    client.post("/login", data={"username": "_guest_admin_", "password": "admin-pass-123"})
    assert client.post(
        f"/admin/starter/topics/{topic.id}/guest-visible",
        data={"guest_visible": "1"},
        follow_redirects=False,
    ).status_code == 204

    test_db.refresh(topic)
    assert topic.guest_visible is True


def test_admin_starter_guest_toggle_markup(client: TestClient, test_db, starter_catalog: None):
    admin = User(username="_guest_ui_admin_", password_hash=hash_password("admin-pass-123"), is_admin=True)
    test_db.add(admin)
    test_db.commit()
    client.post("/login", data={"username": "_guest_ui_admin_", "password": "admin-pass-123"})
    r = client.get("/admin/starter")
    assert r.status_code == 200
    assert b"data-guest-visible-toggle" in r.content
    assert b"onchange=" not in r.content


def test_admin_can_toggle_guest_visible_off(
    client: TestClient,
    test_db,
    starter_catalog: None,
):
    topic = test_db.scalars(select(StarterTopic)).first()
    ensure_starter_topic_slugs(test_db)
    topic.guest_visible = True
    test_db.commit()

    admin = User(username="_guest_off_admin_", password_hash=hash_password("admin-pass-123"), is_admin=True)
    test_db.add(admin)
    test_db.commit()
    client.post("/login", data={"username": "_guest_off_admin_", "password": "admin-pass-123"})
    assert client.post(
        f"/admin/starter/topics/{topic.id}/guest-visible",
        data={"guest_visible": "0"},
        follow_redirects=False,
    ).status_code == 204

    test_db.refresh(topic)
    assert topic.guest_visible is False
