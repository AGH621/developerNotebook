"""Starter data import for a single user."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Entry, Section, Topic, User
from app.seed_data import STARTER_DATA
from app.services.seed import populate_starter_data


def _expected_counts(data: list[dict]) -> tuple[int, int, int]:
    n_topics = len(data)
    n_sections = sum(len(t["sections"]) for t in data)
    n_entries = sum(len(s["entries"]) for t in data for s in t["sections"])
    return n_topics, n_sections, n_entries


def test_populate_creates_expected_rows(test_db: Session):
    user = User(username="seedme", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    exp_t, exp_s, exp_e = _expected_counts(STARTER_DATA)
    counts = populate_starter_data(test_db, user.id)
    test_db.commit()
    assert counts["topics"] == exp_t
    assert counts["sections"] == exp_s
    assert counts["entries"] == exp_e

    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user.id)) == exp_t
    assert (
        test_db.scalar(
            select(func.count(Section.id)).join(Topic).where(Topic.user_id == user.id),
        )
        == exp_s
    )
    assert (
        test_db.scalar(
            select(func.count(Entry.id))
            .join(Section)
            .join(Topic)
            .where(Topic.user_id == user.id),
        )
        == exp_e
    )


def test_seeded_topics_have_slug_and_display_order(test_db: Session):
    user = User(username="ord", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    populate_starter_data(test_db, user.id)
    test_db.commit()
    topics = test_db.scalars(select(Topic).where(Topic.user_id == user.id).order_by(Topic.display_order)).all()
    for i, t in enumerate(topics):
        assert t.display_order == i
        assert t.slug
        assert " " not in t.slug


def test_at_least_one_topic_has_only_default_section(test_db: Session):
    user = User(username="blanktopic", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    populate_starter_data(test_db, user.id)
    test_db.commit()
    topics = test_db.scalars(select(Topic).where(Topic.user_id == user.id)).all()
    assert any(
        len(t.sections) == 1 and t.sections[0].name is None
        for t in topics
    )


def test_seeding_isolated_per_user(test_db: Session):
    u1 = User(username="s1", password_hash=hash_password("a"))
    u2 = User(username="s2", password_hash=hash_password("b"))
    test_db.add_all([u1, u2])
    test_db.commit()
    populate_starter_data(test_db, u1.id)
    test_db.commit()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == u2.id)) == 0
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == u1.id)) > 0
