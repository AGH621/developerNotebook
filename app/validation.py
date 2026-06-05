"""Server-side input length validation constants and helpers."""

from __future__ import annotations

import os

from app.bootstrap import DEFAULT_GUEST_USERNAME

MAX_TOPIC_NAME = 100
MAX_SECTION_NAME = 150
MAX_SECTION_NOTES = 2000
MAX_ENTRY_DESCRIPTION = 300
MAX_ENTRY_COMMAND = 2000
MAX_USERNAME = 50

_RESERVED_USERNAMES = frozenset({"admin", "administrator"})


def truncate(value: str | None, max_length: int) -> str:
    """Strip and truncate ``value`` to ``max_length`` characters."""
    text = (value or "").strip()
    return text[:max_length]


def normalize_username(value: str | None) -> str:
    """Strip and truncate a username to :data:`MAX_USERNAME` characters."""
    return truncate(value, MAX_USERNAME)


def reserved_usernames() -> frozenset[str]:
    """Lowercase usernames that may not be registered or chosen."""
    raw_guest = os.environ.get("GUEST_USERNAME", DEFAULT_GUEST_USERNAME)
    guest = (raw_guest.strip() or DEFAULT_GUEST_USERNAME).lower()
    return _RESERVED_USERNAMES | frozenset({DEFAULT_GUEST_USERNAME.lower(), guest})


def validate_username(name: str) -> str | None:
    """Return an error message if ``name`` is invalid, else ``None``."""
    if not name:
        return "Username is required."
    if name.lower() in reserved_usernames():
        return "That username is reserved."
    return None
