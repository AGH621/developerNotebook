"""ORM model persistence, relationships, and constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Entry, Section, Topic, User


def test_user_topic_section_entry_chain(test_db: Session):
    user = User(username="persist", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()

    topic = Topic(user_id=user.id, name="Git", slug="git", display_order=0)
    test_db.add(topic)
    test_db.flush()
    section = Section(topic_id=topic.id, name="Branches", display_order=0, notes=None)
    test_db.add(section)
    test_db.flush()
    entry = Entry(
        section_id=section.id,
        description="list branches",
        command="git branch",
        display_order=0,
    )
    test_db.add(entry)
    test_db.commit()

    loaded = test_db.scalars(select(User).where(User.id == user.id)).one()
    assert loaded.topics[0].name == "Git"
    assert loaded.topics[0].sections[0].name == "Branches"
    assert loaded.topics[0].sections[0].entries[0].command == "git branch"


def test_section_name_can_be_null(test_db: Session):
    user = User(username="nullsec", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    topic = Topic(user_id=user.id, name="T", slug="t", display_order=0)
    test_db.add(topic)
    test_db.flush()
    section = Section(topic_id=topic.id, name=None, display_order=0, notes=None)
    test_db.add(section)
    test_db.commit()
    sec = test_db.scalars(select(Section).where(Section.id == section.id)).one()
    assert sec.name is None


def test_cascade_delete_topic_removes_sections_and_entries(test_db: Session):
    user = User(username="cascade-u", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    topic = Topic(user_id=user.id, name="T", slug="t", display_order=0)
    test_db.add(topic)
    test_db.flush()
    section = Section(topic_id=topic.id, name="S", display_order=0, notes=None)
    test_db.add(section)
    test_db.flush()
    test_db.add(
        Entry(section_id=section.id, description="d", command="c", display_order=0),
    )
    test_db.commit()
    tid, sid = topic.id, section.id

    test_db.delete(topic)
    test_db.commit()

    assert test_db.scalars(select(Section).where(Section.id == sid)).first() is None
    assert test_db.scalars(select(Entry).where(Entry.section_id == sid)).first() is None
    assert test_db.scalars(select(Topic).where(Topic.id == tid)).first() is None


def test_cascade_delete_section_removes_entries(test_db: Session):
    user = User(username="cascade-s", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    topic = Topic(user_id=user.id, name="T", slug="t", display_order=0)
    test_db.add(topic)
    test_db.flush()
    section = Section(topic_id=topic.id, name="S", display_order=0, notes=None)
    test_db.add(section)
    test_db.flush()
    entry = Entry(section_id=section.id, description="d", command="c", display_order=0)
    test_db.add(entry)
    test_db.commit()
    eid = entry.id

    test_db.delete(section)
    test_db.commit()

    assert test_db.scalars(select(Entry).where(Entry.id == eid)).first() is None


def test_topic_slug_unique_per_user(test_db: Session):
    user = User(username="slug-u", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    test_db.add(Topic(user_id=user.id, name="A", slug="dup", display_order=0))
    test_db.commit()
    test_db.add(Topic(user_id=user.id, name="B", slug="dup", display_order=1))
    with pytest.raises(IntegrityError):
        test_db.commit()
