"""Starter data import for a single user."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Entry, Section, Topic, User
from app.seed_data import STARTER_DATA
from app.services.seed import (
    populate_starter_data,
    starter_topic_indices_available,
    starter_topics_for_user,
    starter_topics_meta,
)


def test_starter_topics_meta_sorted_by_name(test_db: Session, starter_catalog: None):
    meta = starter_topics_meta(test_db)
    names = [str(m["name"]) for m in meta]
    assert names == sorted(names, key=str.casefold)


def _expected_counts(data: list[dict]) -> tuple[int, int, int]:
    n_topics = len(data)
    n_sections = sum(len(t["sections"]) for t in data)
    n_entries = sum(len(s["entries"]) for t in data for s in t["sections"])
    return n_topics, n_sections, n_entries


def test_populate_respects_topic_indices(starter_catalog: None, test_db: Session):
    user = User(username="subset", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    subset = [STARTER_DATA[0]]
    exp_t, exp_s, exp_e = _expected_counts(subset)
    counts = populate_starter_data(test_db, user.id, topic_indices=frozenset({0}))
    test_db.commit()
    assert counts["topics"] == exp_t
    assert counts["sections"] == exp_s
    assert counts["entries"] == exp_e


def test_populate_with_display_order_start(starter_catalog: None, test_db: Session):
    user = User(username="ordstart", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    if len(STARTER_DATA) < 1:
        pytest.skip("needs starter data")
    populate_starter_data(test_db, user.id, topic_indices=frozenset({0}), display_order_start=7)
    test_db.commit()
    topic = test_db.scalars(select(Topic).where(Topic.user_id == user.id)).one()
    assert topic.display_order == 7


def test_starter_topics_for_user_marks_existing(starter_catalog: None, test_db: Session):
    user = User(username="metausr", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    if len(STARTER_DATA) < 1:
        pytest.skip("needs starter data")
    name = str(STARTER_DATA[0]["name"])
    test_db.add(Topic(user_id=user.id, name=name, slug="s", display_order=0))
    test_db.commit()
    rows = starter_topics_for_user(test_db, user.id)
    match = next(r for r in rows if str(r["name"]).casefold() == name.casefold())
    assert match["already_have"] is True


def test_starter_topic_indices_available_excludes_existing(starter_catalog: None, test_db: Session):
    user = User(username="avail", password_hash=hash_password("x"))
    test_db.add(user)
    test_db.commit()
    if len(STARTER_DATA) < 1:
        pytest.skip("needs starter data")
    name = str(STARTER_DATA[0]["name"])
    test_db.add(Topic(user_id=user.id, name=name, slug="s", display_order=0))
    test_db.commit()
    avail = starter_topic_indices_available(test_db, user.id)
    assert 0 not in avail
    if len(STARTER_DATA) > 1:
        assert 1 in avail


def test_populate_creates_expected_rows(starter_catalog: None, test_db: Session):
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


def test_seeded_topics_have_slug_and_display_order(starter_catalog: None, test_db: Session):
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


def test_at_least_one_topic_has_only_default_section(starter_catalog: None, test_db: Session):
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


def test_seeding_isolated_per_user(starter_catalog: None, test_db: Session):
    u1 = User(username="s1", password_hash=hash_password("a"))
    u2 = User(username="s2", password_hash=hash_password("b"))
    test_db.add_all([u1, u2])
    test_db.commit()
    populate_starter_data(test_db, u1.id)
    test_db.commit()
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == u2.id)) == 0
    assert test_db.scalar(select(func.count(Topic.id)).where(Topic.user_id == u1.id)) > 0
