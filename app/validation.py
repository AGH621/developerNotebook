"""Server-side input length validation constants and helpers."""

from __future__ import annotations

MAX_TOPIC_NAME = 100
MAX_SECTION_NAME = 150
MAX_SECTION_NOTES = 2000
MAX_ENTRY_DESCRIPTION = 300
MAX_ENTRY_COMMAND = 2000
MAX_USERNAME = 50


def truncate(value: str | None, max_length: int) -> str:
    """Strip and truncate ``value`` to ``max_length`` characters."""
    text = (value or "").strip()
    return text[:max_length]
