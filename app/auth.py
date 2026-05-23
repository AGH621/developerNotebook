"""Authentication helpers: password hashing and signed session cookies."""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import bcrypt
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.models import User
from app.settings import get_session_timeouts

SESSION_COOKIE_NAME = "session"
_SESSION_SALT = "devnotebook-session"
_DEV_FALLBACK_SECRET = "dev-only-insecure-secret-change-me"
_dev_secret_warning_emitted = False
_SESSION_EXPIRED_LOGIN = "/login?error=" + quote("Your session expired. Please log in again.")

logger = logging.getLogger("devnotebook.auth")


def resolve_session_secret() -> str:
    """Return ``SECRET_KEY`` for signing; enforce in non-dev environments.

    When ``APP_ENV`` is unset or ``dev``, a weak default is allowed (with one
    warning). Production-style environments must set ``SECRET_KEY`` explicitly.
    """
    global _dev_secret_warning_emitted
    raw = os.environ.get("SECRET_KEY")
    if raw:
        return raw
    app_env = os.environ.get("APP_ENV", "dev").strip().lower()
    if app_env not in ("", "dev"):
        raise RuntimeError(
            "SECRET_KEY must be set when APP_ENV is not 'dev' (e.g. production deployments).",
        )
    if not _dev_secret_warning_emitted:
        logger.warning(
            "SECRET_KEY is not set; using an insecure development default. "
            "Set SECRET_KEY before any shared or production deployment.",
        )
        _dev_secret_warning_emitted = True
    return _DEV_FALLBACK_SECRET


def session_cookie_secure() -> bool:
    """Whether session (and CSRF) cookies should use the ``Secure`` flag.

    Defaults to ``True`` in production (APP_ENV=production) unless explicitly
    disabled. In dev mode, defaults to ``False``.
    """
    raw = os.environ.get("SECURE_COOKIES", "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes")
    is_production = os.environ.get("APP_ENV", "dev").strip().lower() == "production"
    return is_production


@lru_cache(maxsize=1)
def _load_common_passwords() -> frozenset[str]:
    path = Path(__file__).resolve().parent / "data" / "common_passwords.txt"
    if not path.exists():
        logger.warning("Common passwords list not found at %s; breach check disabled.", path)
        return frozenset()
    return frozenset(
        line.strip().lower() for line in path.read_text().splitlines() if line.strip()
    )


def validate_password(password: str) -> str | None:
    """Return an error message if ``password`` is too weak, else ``None``."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if password.lower() in _load_common_passwords():
        return "This password is too common. Please choose a different one."
    return None


def _session_serializer() -> URLSafeSerializer:
    """
    Serializer for session cookie payloads.

    Returns
    -------
    URLSafeSerializer
        Configured with ``SECRET_KEY`` (or a dev fallback) and a fixed salt.
    """
    return URLSafeSerializer(resolve_session_secret(), salt=_SESSION_SALT)


def hash_password(password: str) -> str:
    """
    Hash a plaintext password with bcrypt.

    Parameters
    ----------
    password : str
        Plaintext password (UTF-8 encoded before hashing).

    Returns
    -------
    str
        ASCII bcrypt digest suitable for storing in ``User.password_hash``.

    Raises
    ------
    ValueError
        If ``password`` is longer than bcrypt's maximum (~72 bytes) or bcrypt
        rejects the input.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash.

    Parameters
    ----------
    password : str
        Candidate password supplied by the user.
    password_hash : str
        Stored digest from ``hash_password``.

    Returns
    -------
    bool
        ``True`` if the password matches, ``False`` otherwise (including when
        the hash format is invalid).
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def _remaining_absolute_seconds(iat: int, absolute_minutes: int, now: float) -> int:
    return max(0, int(iat + absolute_minutes * 60 - now))


def _session_expired(
    payload: dict[str, int],
    absolute_minutes: int,
    idle_minutes: int,
    now: float,
) -> bool:
    iat = payload["iat"]
    last_activity = payload["last_activity"]
    if now - iat > absolute_minutes * 60:
        return True
    return now - last_activity > idle_minutes * 60


def _set_session_cookie(
    response: Response,
    payload: dict[str, int],
    absolute_minutes: int,
) -> None:
    now = time.time()
    max_age = _remaining_absolute_seconds(payload["iat"], absolute_minutes, now)
    token = _session_serializer().dumps(payload)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=max_age,
        secure=session_cookie_secure(),
    )


def _load_session_payload(raw: str) -> dict[str, int] | None:
    try:
        payload = _session_serializer().loads(raw)
    except BadSignature:
        logger.debug("Session cookie signature invalid or tampered")
        return None
    if not isinstance(payload, dict):
        return None
    user_id = payload.get("user_id")
    cookie_ver = payload.get("session_version")
    iat = payload.get("iat")
    last_activity = payload.get("last_activity")
    if not all(
        isinstance(v, int)
        for v in (user_id, cookie_ver, iat, last_activity)
    ):
        return None
    return {
        "user_id": user_id,
        "session_version": cookie_ver,
        "iat": iat,
        "last_activity": last_activity,
    }


def create_session(response: Response, user: User, db: Session) -> None:
    """Sign ``user`` identity and set the HTTP-only session cookie on ``response``."""
    absolute_minutes, _idle_minutes = get_session_timeouts(db)
    now = int(time.time())
    payload = {
        "user_id": user.id,
        "session_version": user.session_version,
        "iat": now,
        "last_activity": now,
    }
    _set_session_cookie(response, payload, absolute_minutes)


def refresh_session_cookie(
    response: Response,
    user: User,
    payload: dict[str, int],
    db: Session,
) -> None:
    """Extend idle timeout by updating ``last_activity`` on the session cookie."""
    absolute_minutes, _idle_minutes = get_session_timeouts(db)
    now = int(time.time())
    new_payload = {
        "user_id": user.id,
        "session_version": user.session_version,
        "iat": payload["iat"],
        "last_activity": now,
    }
    _set_session_cookie(response, new_payload, absolute_minutes)


def _resolve_session(request: Request, db: Session) -> tuple[User, dict[str, int]] | None:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None
    payload = _load_session_payload(raw)
    if payload is None:
        return None

    absolute_minutes, idle_minutes = get_session_timeouts(db)
    now = time.time()
    if _session_expired(payload, absolute_minutes, idle_minutes, now):
        logger.info("Session expired user_id=%s", payload["user_id"])
        return None

    user = db.scalars(select(User).where(User.id == payload["user_id"])).first()
    if user is None:
        logger.debug("Session references missing user id=%s", payload["user_id"])
        return None
    if user.session_version != payload["session_version"]:
        logger.info("Session rejected stale session_version user_id=%s", user.id)
        return None
    if user.is_suspended:
        logger.info("Session denied for suspended user id=%s", user.id)
        return None
    return user, payload


def get_current_user(request: Request, db: Session) -> User | None:
    """Load the logged-in user from the session cookie, if valid."""
    result = _resolve_session(request, db)
    if result is None:
        return None
    user, _payload = result
    return user


def require_auth(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: require a valid session or redirect to login."""
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        raise HTTPException(
            status_code=303,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )

    result = _resolve_session(request, db)
    if result is None:
        payload = _load_session_payload(raw)
        absolute_minutes, idle_minutes = get_session_timeouts(db)
        if payload is not None and _session_expired(
            payload,
            absolute_minutes,
            idle_minutes,
            time.time(),
        ):
            location = _SESSION_EXPIRED_LOGIN
        else:
            location = "/login"
        raise HTTPException(
            status_code=303,
            detail="Not authenticated",
            headers={"Location": location},
        )
    user, payload = result
    refresh_session_cookie(response, user, payload, db)
    return user


def require_admin(user: User = Depends(require_auth)) -> User:
    """FastAPI dependency: require an authenticated admin session.

    Raises
    ------
    HTTPException
        **403** when the user is not an administrator.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def require_can_write(user: User = Depends(require_auth)) -> User:
    """FastAPI dependency: require a session that may modify notebook content."""
    if user.is_guest:
        raise HTTPException(status_code=403, detail="Read-only account.")
    return user
