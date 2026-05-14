"""Entry CRUD and reorder routes."""

from __future__ import annotations

from starlette.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Entry, Section, Topic, User

from tests.conftest import TEST_PASSWORD


@pytest.fixture
def section_with_entries(authenticated_client: TestClient, test_db: Session) -> Section:
    authenticated_client.post("/topics", data={"name": "K8s"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "K8s")).one()
    authenticated_client.post(f"/topics/{topic.id}/sections", data={"name": "Pods"})
    return test_db.scalars(
        select(Section).where(Section.topic_id == topic.id, Section.name == "Pods"),
    ).one()


def test_post_entry(section_with_entries: Section, authenticated_client: TestClient, test_db: Session) -> None:
    r = authenticated_client.post(
        f"/sections/{section_with_entries.id}/entries",
        data={"description": "List pods", "command": "kubectl get pods"},
    )
    assert r.status_code == 200
    assert b"entry-row" in r.content
    row = test_db.scalars(
        select(Entry).where(Entry.section_id == section_with_entries.id, Entry.description == "List pods"),
    ).first()
    assert row is not None


def test_get_entry_edit_partial(section_with_entries: Section, authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post(
        f"/sections/{section_with_entries.id}/entries",
        data={"description": "d", "command": "c"},
    )
    entry = test_db.scalars(select(Entry).where(Entry.section_id == section_with_entries.id)).first()
    assert entry is not None
    r = authenticated_client.get(f"/entries/{entry.id}/edit")
    assert r.status_code == 200
    assert b"entry-row--editing" in r.content


def test_put_entry_updates(section_with_entries: Section, authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post(
        f"/sections/{section_with_entries.id}/entries",
        data={"description": "old", "command": "oldcmd"},
    )
    entry = test_db.scalars(select(Entry).where(Entry.section_id == section_with_entries.id)).one()
    r = authenticated_client.put(
        f"/entries/{entry.id}",
        data={"description": "new desc", "command": "new cmd"},
    )
    assert r.status_code == 200
    assert b"new desc" in r.content
    test_db.refresh(entry)
    assert entry.description == "new desc"
    assert entry.command == "new cmd"


def test_delete_entry(section_with_entries: Section, authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post(
        f"/sections/{section_with_entries.id}/entries",
        data={"description": "x", "command": "y"},
    )
    entry = test_db.scalars(select(Entry).where(Entry.section_id == section_with_entries.id)).one()
    eid = entry.id
    r = authenticated_client.delete(f"/entries/{eid}")
    assert r.status_code == 200
    assert test_db.scalars(select(Entry).where(Entry.id == eid)).first() is None


def test_put_entries_reorder(section_with_entries: Section, authenticated_client: TestClient, test_db: Session) -> None:
    authenticated_client.post(
        f"/sections/{section_with_entries.id}/entries",
        data={"description": "a", "command": "1"},
    )
    authenticated_client.post(
        f"/sections/{section_with_entries.id}/entries",
        data={"description": "b", "command": "2"},
    )
    ids = [
        e.id
        for e in test_db.scalars(
            select(Entry).where(Entry.section_id == section_with_entries.id).order_by(Entry.display_order),
        ).all()
    ]
    rev = list(reversed(ids))
    r = authenticated_client.put("/entries/reorder", data={"entry_order": ",".join(str(i) for i in rev)})
    assert r.status_code == 204
    fresh = test_db.scalars(
        select(Entry).where(Entry.section_id == section_with_entries.id).order_by(Entry.display_order),
    ).all()
    assert [e.id for e in fresh] == rev


def test_entry_foreign_user_forbidden(client: TestClient, test_db: Session, register_invite: str) -> None:
    owner = User(username="ent-owner", password_hash=hash_password("a"))
    test_db.add(owner)
    test_db.commit()
    topic = Topic(user_id=owner.id, name="T", slug="t", display_order=0)
    test_db.add(topic)
    test_db.flush()
    section = Section(topic_id=topic.id, name="S", display_order=0, notes=None)
    test_db.add(section)
    test_db.flush()
    entry = Entry(section_id=section.id, description="d", command="c", display_order=0)
    test_db.add(entry)
    test_db.commit()

    client.post(
        "/register",
        data={"username": "ent-intruder", "password": TEST_PASSWORD, "invite_code": register_invite},
    )
    r = client.put(f"/entries/{entry.id}", data={"description": "z", "command": "z"})
    assert r.status_code == 404
