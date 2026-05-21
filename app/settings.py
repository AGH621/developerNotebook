"""Application-wide settings stored in the database."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AppSettings

SETTINGS_ROW_ID = 1
DEFAULT_SESSION_ABSOLUTE_MINUTES = 20_160  # 14 days
DEFAULT_SESSION_IDLE_MINUTES = 60
SESSION_IDLE_MIN_MINUTES = 5
SESSION_IDLE_MAX_MINUTES = 10_080  # 7 days
SESSION_ABSOLUTE_MAX_MINUTES = 525_600  # 1 year

_timeout_cache: tuple[int, int] | None = None


def invalidate_settings_cache() -> None:
    """Clear cached session timeout values after an admin update."""
    global _timeout_cache
    _timeout_cache = None


def ensure_app_settings(db: Session) -> AppSettings:
    """Ensure the singleton settings row exists; return it."""
    row = db.get(AppSettings, SETTINGS_ROW_ID)
    if row is not None:
        return row
    row = AppSettings(
        id=SETTINGS_ROW_ID,
        session_absolute_minutes=DEFAULT_SESSION_ABSOLUTE_MINUTES,
        session_idle_minutes=DEFAULT_SESSION_IDLE_MINUTES,
    )
    db.add(row)
    db.flush()
    return row


def get_app_settings(db: Session) -> AppSettings:
    """Load application settings, creating defaults if missing."""
    row = db.get(AppSettings, SETTINGS_ROW_ID)
    if row is None:
        row = ensure_app_settings(db)
        db.commit()
        db.refresh(row)
    return row


def get_session_timeouts(db: Session) -> tuple[int, int]:
    """Return ``(absolute_minutes, idle_minutes)``, with a small in-process cache."""
    global _timeout_cache
    if _timeout_cache is not None:
        return _timeout_cache
    settings = get_app_settings(db)
    _timeout_cache = (
        settings.session_absolute_minutes,
        settings.session_idle_minutes,
    )
    return _timeout_cache


def validate_session_timeout_minutes(
    absolute_minutes: int,
    idle_minutes: int,
) -> str | None:
    """Return an error message if the pair is invalid, else ``None``."""
    if idle_minutes < SESSION_IDLE_MIN_MINUTES or idle_minutes > SESSION_IDLE_MAX_MINUTES:
        return (
            f"Idle timeout must be between {SESSION_IDLE_MIN_MINUTES} and "
            f"{SESSION_IDLE_MAX_MINUTES} minutes."
        )
    if (
        absolute_minutes < idle_minutes
        or absolute_minutes > SESSION_ABSOLUTE_MAX_MINUTES
    ):
        return (
            f"Absolute timeout must be at least {idle_minutes} minutes and at most "
            f"{SESSION_ABSOLUTE_MAX_MINUTES} minutes."
        )
    return None
