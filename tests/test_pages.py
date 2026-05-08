"""Full-page routes (home, topic, welcome)."""

from __future__ import annotations

from starlette.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Topic, User


def test_home_lists_topic_cards(seeded_client: TestClient, test_db: Session) -> None:
    r = seeded_client.get("/")
    assert r.status_code == 200
    assert b"topic-card" in r.content
    user = test_db.scalars(select(User).where(User.username == "testuser")).one()
    n = test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id))
    assert n and n > 0


def test_topic_page_with_slug(seeded_client: TestClient, test_db: Session) -> None:
    user = test_db.scalars(select(User).where(User.username == "testuser")).one()
    topic = test_db.scalars(select(Topic).where(Topic.user_id == user.id)).first()
    assert topic is not None
    r = seeded_client.get(f"/topic/{topic.slug}")
    assert r.status_code == 200
    assert topic.name.encode() in r.content


def test_welcome_get_after_register(client: TestClient, test_db: Session) -> None:
    client.post("/register", data={"username": "wel", "password": "pw"})
    r = client.get("/welcome")
    assert r.status_code == 200
    assert b"Welcome" in r.content


def test_welcome_post_template_seeds(client: TestClient, test_db: Session) -> None:
    client.post("/register", data={"username": "tpl", "password": "pw"})
    r = client.post("/welcome", data={"choice": "template"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    user = test_db.scalars(select(User).where(User.username == "tpl")).one()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) > 0


def test_welcome_post_blank_skips_seed(client: TestClient, test_db: Session) -> None:
    client.post("/register", data={"username": "blk", "password": "pw"})
    r = client.post("/welcome", data={"choice": "blank"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    user = test_db.scalars(select(User).where(User.username == "blk")).one()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == 0
