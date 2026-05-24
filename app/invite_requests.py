"""Validation helpers for public invitation request submissions."""

from __future__ import annotations

import re

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    """Strip and lowercase an email address."""
    return raw.strip().lower()


def validate_request_email(email: str) -> str | None:
    """Return an error message if ``email`` is invalid, else ``None``."""
    if not email:
        return "Email is required."
    if len(email) > 254:
        return "Email is too long."
    if not _EMAIL_RE.match(email):
        return "Enter a valid email address."
    return None


def normalize_optional_text(raw: str, max_len: int) -> str | None:
    """Trim text; return ``None`` when empty after trim."""
    text = raw.strip()
    if not text:
        return None
    if len(text) > max_len:
        return text[:max_len]
    return text
