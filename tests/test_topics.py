"""Topic CRUD and reorder (HTMX partials)."""

from __future__ import annotations

from starlette.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Section, Topic, User

from tests.conftest import TEST_PASSWORD, TEST_USERNAME


def test_post_topics_creates_default_section(authenticated_client: TestClient, test_db: Session) -> None:
    r = authenticated_client.post("/topics", data={"name": "Docker"})
    assert r.status_code == 200
    assert b"topic-card" in r.content
    topic = test_db.scalars(select(Topic).where(Topic.name == "Docker")).one()
    secs = test_db.scalars(select(Section).where(Section.topic_id == topic.id)).all()
    assert len(secs) == 1
    assert secs[0].name is None


def test_put_topic_renames_and_slug(authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post("/topics", data={"name": "Old"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "Old")).one()
    tid = topic.id
    r = authenticated_client.put(f"/topics/{tid}", data={"name": "Renamed Topic"})
    assert r.status_code == 200
    assert b"Renamed Topic" in r.content
    test_db.refresh(topic)
    assert topic.name == "Renamed Topic"
    assert topic.slug.startswith("renamed")


def test_delete_topic_cascades(authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post("/topics", data={"name": "Gone"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "Gone")).one()
    tid = topic.id
    authenticated_client.delete(f"/topics/{tid}")
    assert test_db.scalars(select(Topic).where(Topic.id == tid)).first() is None


def test_put_topics_reorder(authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post("/topics", data={"name": "First"})
    authenticated_client.post("/topics", data={"name": "Second"})
    user = test_db.scalars(select(User).where(User.username == TEST_USERNAME)).one()
    ids = [t.id for t in test_db.scalars(select(Topic).where(Topic.user_id == user.id)).all()]
    assert len(ids) >= 2
    rev = list(reversed(ids))
    body = ",".join(str(i) for i in rev)
    r = authenticated_client.put("/topics/reorder", data={"topic_order": body})
    assert r.status_code == 204
    fresh = test_db.scalars(
        select(Topic).where(Topic.user_id == user.id).order_by(Topic.display_order),
    ).all()
    assert [t.id for t in fresh] == rev


def test_user_cannot_access_other_users_topic(client: TestClient, test_db: Session, register_invite: str) -> None:
    u1 = User(username="alice", password_hash=hash_password("a"))
    test_db.add(u1)
    test_db.commit()
    topic = Topic(user_id=u1.id, name="Private", slug="private", display_order=0)
    test_db.add(topic)
    test_db.flush()
    test_db.add(Section(topic_id=topic.id, name=None, display_order=0, notes=None))
    test_db.commit()

    client.post(
        "/register",
        data={"username": "bob", "password": TEST_PASSWORD, "invite_code": register_invite},
    )
    r = client.put(f"/topics/{topic.id}", data={"name": "Hack"})
    assert r.status_code == 404


@pytest.fixture
def two_users_clients(client: TestClient, test_db: Session, register_invite: str):
    """Client logged in as bob2; alice2 owns a topic bob2 must not modify."""
    alice = User(username="alice2", password_hash=hash_password("a"))
    test_db.add(alice)
    test_db.commit()
    topic = Topic(user_id=alice.id, name="Alone", slug="alone", display_order=0)
    test_db.add(topic)
    test_db.commit()
    client.post(
        "/register",
        data={"username": "bob2", "password": "password", "invite_code": register_invite},
    )
    return client, topic.id


def test_user_cannot_rename_foreign_topic(two_users_clients) -> None:
    c, tid = two_users_clients
    r = c.put(f"/topics/{tid}", data={"name": "Nope"})
    assert r.status_code == 404
