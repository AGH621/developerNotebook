"""Full-page routes (home, topic, welcome)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Topic, User
from app.seed_data import STARTER_DATA
from app.services.seed import starter_catalog_topic_count


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


def test_welcome_get_after_register(client: TestClient, test_db: Session, register_invite: str) -> None:
    client.post(
        "/register",
        data={"username": "wel", "password": "pw-longer", "invite_code": register_invite},
    )
    r = client.get("/welcome")
    assert r.status_code == 200
    assert b"Welcome" in r.content
    assert b"Seed selected topics" in r.content


def test_welcome_post_template_seeds(
    client: TestClient,
    test_db: Session,
    register_invite: str,
    starter_catalog: None,
) -> None:
    client.post(
        "/register",
        data={"username": "tpl", "password": "pw-longer", "invite_code": register_invite},
    )
    n = starter_catalog_topic_count(test_db)
    data = {"choice": "template", "topic": [str(i) for i in range(n)]}
    r = client.post("/welcome", data=data, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    user = test_db.scalars(select(User).where(User.username == "tpl")).one()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == n


def test_welcome_post_template_subset(
    client: TestClient,
    test_db: Session,
    register_invite: str,
    starter_catalog: None,
) -> None:
    client.post(
        "/register",
        data={"username": "sub", "password": "pw-longer", "invite_code": register_invite},
    )
    r = client.post("/welcome", data={"choice": "template", "topic": "0"}, follow_redirects=False)
    assert r.status_code == 303
    user = test_db.scalars(select(User).where(User.username == "sub")).one()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == 1


def test_welcome_post_template_requires_topic(client: TestClient, test_db: Session, register_invite: str) -> None:
    client.post(
        "/register",
        data={"username": "needtp", "password": "pw-longer", "invite_code": register_invite},
    )
    r = client.post("/welcome", data={"choice": "template"}, follow_redirects=False)
    assert r.status_code == 400
    user = test_db.scalars(select(User).where(User.username == "needtp")).one()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == 0


def test_welcome_post_blank_skips_seed(client: TestClient, test_db: Session, register_invite: str) -> None:
    client.post(
        "/register",
        data={"username": "blk", "password": "pw-longer", "invite_code": register_invite},
    )
    r = client.post("/welcome", data={"choice": "blank"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/"
    user = test_db.scalars(select(User).where(User.username == "blk")).one()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == 0


def test_seed_topics_get_ok_when_authenticated(client: TestClient, test_db: Session, register_invite: str) -> None:
    client.post(
        "/register",
        data={"username": "seedpg", "password": "pw-longer", "invite_code": register_invite},
    )
    r = client.get("/seed-topics")
    assert r.status_code == 200
    assert b"Add starter cheatsheets" in r.content


def test_seed_topics_post_appends_new_topic(
    client: TestClient,
    test_db: Session,
    register_invite: str,
    starter_catalog: None,
) -> None:
    if len(STARTER_DATA) < 2:
        pytest.skip("needs multiple starter topics")
    client.post(
        "/register",
        data={"username": "apd", "password": "pw-longer", "invite_code": register_invite},
    )
    user = test_db.scalars(select(User).where(User.username == "apd")).one()
    existing_name = str(STARTER_DATA[0]["name"])
    test_db.add(
        Topic(user_id=user.id, name=existing_name, slug="existing-slug", display_order=10),
    )
    test_db.commit()

    r_bad = client.post("/seed-topics", data={"topic": "0"}, follow_redirects=False)
    assert r_bad.status_code == 400

    r_ok = client.post("/seed-topics", data={"topic": "1"}, follow_redirects=False)
    assert r_ok.status_code == 303
    assert r_ok.headers.get("location") == "/"

    titles = test_db.scalars(select(Topic.name).where(Topic.user_id == user.id)).all()
    assert str(STARTER_DATA[1]["name"]) in [str(t) for t in titles]

    new_topic = test_db.scalars(
        select(Topic).where(Topic.user_id == user.id, Topic.name == str(STARTER_DATA[1]["name"])),
    ).one()
    assert new_topic.display_order == 11
