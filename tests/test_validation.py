"""Username and input validation helpers."""

from __future__ import annotations

from app.bootstrap import DEFAULT_GUEST_USERNAME
from app.validation import MAX_USERNAME, normalize_username, reserved_usernames, validate_username


def test_normalize_username_truncates_and_strips():
    assert normalize_username("  hello world  ") == "hello world"
    assert len(normalize_username("x" * 60)) == MAX_USERNAME


def test_validate_username_rejects_empty():
    assert validate_username("") == "Username is required."


def test_validate_username_rejects_reserved_names():
    for name in ("admin", "Admin", "ADMINISTRATOR", DEFAULT_GUEST_USERNAME):
        assert validate_username(name) == "That username is reserved."


def test_validate_username_accepts_normal_name():
    assert validate_username("alice") is None


def test_reserved_usernames_includes_guest_env(monkeypatch):
    monkeypatch.setenv("GUEST_USERNAME", "browse-only")
    assert "browse-only" in reserved_usernames()
