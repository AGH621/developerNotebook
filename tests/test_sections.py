"""Section CRUD and reorder routes."""

from __future__ import annotations

from starlette.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Section, Topic, User

from tests.conftest import TEST_PASSWORD


@pytest.fixture
def topic_with_sections(authenticated_client: TestClient, test_db: Session) -> Topic:
    authenticated_client.post("/topics", data={"name": "Main"})
    return test_db.scalars(select(Topic).where(Topic.name == "Main")).one()


def test_post_section_named(topic_with_sections: Topic, authenticated_client: TestClient, test_db: Session) -> None:
    r = authenticated_client.post(f"/topics/{topic_with_sections.id}/sections", data={"name": "Install"})
    assert r.status_code == 200
    assert b"topic-section" in r.content
    assert (
        test_db.scalars(
            select(Section).where(Section.topic_id == topic_with_sections.id, Section.name == "Install"),
        ).first()
        is not None
    )


def test_single_unnamed_section_edit_exposes_name_field(
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    """Lone default section must allow naming (was hidden-input only)."""
    authenticated_client.post("/topics", data={"name": "Solo"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "Solo")).one()
    sec = test_db.scalars(
        select(Section).where(Section.topic_id == topic.id),
    ).one()
    assert sec.name is None
    r = authenticated_client.get(f"/sections/{sec.id}/edit")
    assert r.status_code == 200
    html = r.text
    assert 'name="name"' in html and 'type="text"' in html
    authenticated_client.put(f"/sections/{sec.id}", data={"name": "Named!", "notes": ""})
    test_db.refresh(sec)
    assert sec.name == "Named!"


def test_post_second_named_section_returns_sidebar_oob(
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    authenticated_client.post("/topics", data={"name": "Toc"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "Toc")).one()
    only = test_db.scalars(select(Section).where(Section.topic_id == topic.id)).one()
    authenticated_client.put(f"/sections/{only.id}", data={"name": "First", "notes": ""})
    r = authenticated_client.post(f"/topics/{topic.id}/sections", data={"name": "Second"})
    assert r.status_code == 200
    html = r.text
    assert 'id="topic-sidebar-root"' in html and 'hx-swap-oob="true"' in html
    assert "topic-sidebar__link" in html
    assert "First" in html and "Second" in html


def test_delete_named_section_oob_hides_sidebar_when_under_two_named(
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    authenticated_client.post("/topics", data={"name": "Trm"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "Trm")).one()
    s1 = test_db.scalars(select(Section).where(Section.topic_id == topic.id)).one()
    authenticated_client.put(f"/sections/{s1.id}", data={"name": "A", "notes": ""})
    authenticated_client.post(f"/topics/{topic.id}/sections", data={"name": "B"})
    b_sec = test_db.scalars(
        select(Section).where(Section.topic_id == topic.id, Section.name == "B"),
    ).one()
    r = authenticated_client.delete(f"/sections/{b_sec.id}")
    assert r.status_code == 200
    html = r.text
    assert 'id="topic-sidebar-root"' in html and 'hx-swap-oob="true"' in html
    assert '<aside class="topic-sidebar"' not in html


def test_put_section_rename(topic_with_sections: Topic, authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post(f"/topics/{topic_with_sections.id}/sections", data={"name": "OldSec"})
    sec = test_db.scalars(
        select(Section).where(Section.topic_id == topic_with_sections.id, Section.name == "OldSec"),
    ).one()
    r = authenticated_client.put(f"/sections/{sec.id}", data={"name": "NewSec", "notes": ""})
    assert r.status_code == 200
    test_db.refresh(sec)
    assert sec.name == "NewSec"


def test_delete_section_removes_entries(
    topic_with_sections: Topic,
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    authenticated_client.post(f"/topics/{topic_with_sections.id}/sections", data={"name": "Tmp"})
    sec = test_db.scalars(
        select(Section).where(Section.topic_id == topic_with_sections.id, Section.name == "Tmp"),
    ).one()
    authenticated_client.post(f"/sections/{sec.id}/entries", data={"description": "d", "command": "c"})
    sid = sec.id
    r = authenticated_client.delete(f"/sections/{sid}")
    assert r.status_code == 200
    assert test_db.scalars(select(Section).where(Section.id == sid)).first() is None


def test_put_sections_reorder(topic_with_sections: Topic, authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post(f"/topics/{topic_with_sections.id}/sections", data={"name": "A"})
    authenticated_client.post(f"/topics/{topic_with_sections.id}/sections", data={"name": "B"})
    ids = [
        s.id
        for s in test_db.scalars(
            select(Section).where(Section.topic_id == topic_with_sections.id).order_by(Section.display_order),
        ).all()
    ]
    assert len(ids) >= 2
    rev = list(reversed(ids))
    r = authenticated_client.put("/sections/reorder", data={"section_order": ",".join(str(i) for i in rev)})
    assert r.status_code == 204
    fresh = test_db.scalars(
        select(Section).where(Section.topic_id == topic_with_sections.id).order_by(Section.display_order),
    ).all()
    assert [s.id for s in fresh] == rev


def test_section_foreign_user_forbidden(client: TestClient, test_db: Session) -> None:
    owner = User(username="sec-owner", password_hash=hash_password("a"))
    test_db.add(owner)
    test_db.commit()
    topic = Topic(user_id=owner.id, name="T", slug="t", display_order=0)
    test_db.add(topic)
    test_db.flush()
    section = Section(topic_id=topic.id, name="S", display_order=0, notes=None)
    test_db.add(section)
    test_db.commit()

    client.post("/register", data={"username": "sec-intruder", "password": TEST_PASSWORD})
    r = client.put(f"/sections/{section.id}", data={"name": "X", "notes": ""})
    assert r.status_code == 404
