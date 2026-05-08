"""Authentication helpers: password hashing and signed session cookies."""

from __future__ import annotations

import logging
import os

import bcrypt
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.models import User

SESSION_COOKIE_NAME = "session"
_SESSION_SALT = "devnotebook-session"

logger = logging.getLogger("devnotebook.auth")


def _session_serializer() -> URLSafeSerializer:
    """
    FIXME: Generate proper secret in .env (create .env if needed)
    Serializer for session cookie payloads.

    Returns
    -------
    URLSafeSerializer
        Configured with ``SECRET_KEY`` (or a dev fallback) and a fixed salt.
    """
    secret = os.environ.get(
        "SECRET_KEY",
        "dev-insecure-default-change-before-production",
    )
    return URLSafeSerializer(secret, salt=_SESSION_SALT)


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


def create_session(response: Response, user_id: int) -> None:
    """Sign ``user_id`` and set the HTTP-only session cookie on ``response``.

    Parameters
    ----------
    response : Response
        Outgoing response (e.g. redirect) that will carry ``Set-Cookie``.
    user_id : int
        Primary key of the authenticated user.

    Returns
    -------
    None
        Mutates ``response`` in place.
    """
    token = _session_serializer().dumps({"user_id": user_id})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=60 * 60 * 24 * 14,
    )


def get_current_user(request: Request, db: Session) -> User | None:
    """Load the logged-in user from the session cookie, if valid.

    Parameters
    ----------
    request : Request
        Incoming request; the session cookie is read from it.
    db : Session
        Database session used to load ``User`` by primary key.

    Returns
    -------
    User or None
        The user when the cookie is present, well-formed, and refers to an
        existing row; otherwise ``None``.
    """
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None
    try:
        payload = _session_serializer().loads(raw)
    except BadSignature:
        logger.debug("Session cookie signature invalid or tampered")
        return None
    user_id = payload.get("user_id") if isinstance(payload, dict) else None
    if not isinstance(user_id, int):
        return None
    user = db.scalars(select(User).where(User.id == user_id)).first()
    if user is None:
        logger.debug("Session references missing user id=%s", user_id)
    return user


def require_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: require a valid session or redirect to login.

    Parameters
    ----------
    request : Request
        Current request.
    db : Session
        Database session from :func:`app.database.get_db`.

    Returns
    -------
    User
        The authenticated user.

    Raises
    ------
    HTTPException
        With status 303 and ``Location: /login`` when there is no valid session.
    """
    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=303,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )
    return user
