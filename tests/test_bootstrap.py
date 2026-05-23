"""Startup bootstrap: env admin account and starter catalog seed."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.bootstrap import bootstrap_admin_from_env, bootstrap_guest_user, run_startup_tasks, seed_starter_catalog_if_empty
from app.models import StarterEntry, StarterTopic, User

_MINI_STARTER: list[dict] = [
    {
        "name": "TinyTopic",
        "sections": [
            {
                "name": "TinySection",
                "entries": [
                    {"description": "Do thing", "command": "cmd --flag"},
                ],
            },
        ],
    },
]


def test_bootstrap_admin_skips_when_env_unset(monkeypatch: pytest.MonkeyPatch, test_db: Session):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    bootstrap_admin_from_env(test_db)
    test_db.commit()
    assert test_db.scalars(select(User)).first() is None


def test_bootstrap_admin_creates_user(monkeypatch: pytest.MonkeyPatch, test_db: Session):
    monkeypatch.setenv("ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "phase-one-secret!")
    bootstrap_admin_from_env(test_db)
    test_db.commit()
    u = test_db.scalars(select(User).where(User.username == "bootstrap-admin")).one()
    assert u.is_admin is True
    assert u.is_suspended is False
    assert verify_password("phase-one-secret!", u.password_hash)


def test_bootstrap_admin_rejects_short_password(
    monkeypatch: pytest.MonkeyPatch,
    test_db: Session,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv("ADMIN_USERNAME", "shorty")
    monkeypatch.setenv("ADMIN_PASSWORD", "1234567")
    with caplog.at_level("ERROR", logger="devnotebook.bootstrap"):
        bootstrap_admin_from_env(test_db)
        test_db.commit()
    assert "8 characters" in caplog.text
    assert "NOT created" in caplog.text
    result = test_db.scalars(select(User).where(User.username == "shorty")).first()
    assert result is None


def test_bootstrap_admin_promotes_existing_without_password_change(
    monkeypatch: pytest.MonkeyPatch,
    test_db: Session,
):
    test_db.add(
        User(
            username="existing",
            password_hash=hash_password("unchanged-original"),
            is_admin=False,
        ),
    )
    test_db.commit()

    monkeypatch.setenv("ADMIN_USERNAME", "existing")
    monkeypatch.setenv("ADMIN_PASSWORD", "env-would-be-different")

    bootstrap_admin_from_env(test_db)
    test_db.commit()

    u = test_db.scalars(select(User).where(User.username == "existing")).one()
    assert u.is_admin is True
    assert verify_password("unchanged-original", u.password_hash)
    assert not verify_password("env-would-be-different", u.password_hash)


def test_bootstrap_admin_partial_env_warns_and_skips(
    monkeypatch: pytest.MonkeyPatch,
    test_db: Session,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setenv("ADMIN_USERNAME", "solo-name")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with caplog.at_level("WARNING", logger="devnotebook.bootstrap"):
        bootstrap_admin_from_env(test_db)
        test_db.commit()
    assert "must both be set" in caplog.text
    assert test_db.scalars(select(User)).first() is None


def test_seed_starter_catalog_inserts_when_empty(test_db: Session):
    seeded = seed_starter_catalog_if_empty(test_db, _MINI_STARTER)
    assert seeded is True
    test_db.commit()
    tt = test_db.scalars(select(StarterTopic)).one()
    assert tt.name == "TinyTopic"


def test_seed_starter_catalog_idempotent(test_db: Session):
    seed_starter_catalog_if_empty(test_db, _MINI_STARTER)
    test_db.commit()
    again = seed_starter_catalog_if_empty(test_db, _MINI_STARTER)
    assert again is False
    assert len(test_db.scalars(select(StarterTopic)).all()) == 1


def test_run_startup_tasks_runs_admin_and_seed(monkeypatch: pytest.MonkeyPatch, test_db: Session):
    monkeypatch.setenv("ADMIN_USERNAME", "ops")
    monkeypatch.setenv("ADMIN_PASSWORD", "ops-pass-please")
    run_startup_tasks(test_db, starter_data=_MINI_STARTER)
    test_db.commit()

    ops = test_db.scalars(select(User).where(User.username == "ops")).one()
    assert ops.is_admin

    topics = test_db.scalars(select(StarterTopic)).all()
    entries = test_db.scalars(select(StarterEntry)).all()
    assert len(topics) == 1
    assert len(entries) == 1


def test_bootstrap_guest_user_creates_read_only_account(test_db: Session):
    bootstrap_guest_user(test_db)
    test_db.commit()
    guest = test_db.scalars(select(User).where(User.is_guest.is_(True))).one()
    assert guest.is_admin is False
    assert guest.is_suspended is False


def test_bootstrap_guest_user_is_idempotent(test_db: Session):
    bootstrap_guest_user(test_db)
    test_db.commit()
    bootstrap_guest_user(test_db)
    test_db.commit()
    guests = test_db.scalars(select(User).where(User.is_guest.is_(True))).all()
    assert len(guests) == 1
