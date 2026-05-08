"""HTML page routes: authentication and (later) home, welcome, and topic pages."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    get_current_user,
    hash_password,
    require_auth,
    verify_password,
)
from app.database import get_db
from app.models import Topic, User
from app.services.seed import populate_starter_data
from app.templating import templates

router = APIRouter()
auth_log = logging.getLogger("devnotebook.auth")


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/login")
async def login_get(request: Request, db: Session = Depends(get_db)):
    """Show the login form.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    db : Session
        Database session for optional session lookup.

    Returns
    -------
    TemplateResponse
        Rendered ``login.html`` with optional query-string error text.
    RedirectResponse
        Redirects to ``/`` when a session is already valid.
    """
    user = get_current_user(request, db)
    if user is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    err = request.query_params.get("error")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": err, "user": None},
    )


@router.post("/login")
async def login_post(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    """Authenticate a user and establish a session.

    Parameters
    ----------
    request : Request
        The incoming request (used for template rendering on failure).
    username : str
        Submitted ``username`` field.
    password : str
        Submitted ``password`` field.
    db : Session
        Database session provided by dependency injection.

    Returns
    -------
    RedirectResponse
        Redirects to ``/`` on success.
    TemplateResponse
        Re-renders ``login.html`` with an error message on failure.
    """
    name = username.strip()
    if not name or not password:
        auth_log.warning("Login failed empty username or password")
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Username and password are required.",
                "user": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    row = db.scalars(select(User).where(User.username == name)).first()
    if row is None:
        auth_log.warning("Login failed unknown user username=%s", name)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Unknown username or incorrect password.",
                "user": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not verify_password(password, row.password_hash):
        auth_log.warning("Login failed bad password username=%s", name)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Unknown username or incorrect password.",
                "user": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    auth_log.info("Login succeeded username=%s user_id=%s", name, row.id)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, row.id)
    return response


@router.get("/register")
async def register_get(request: Request, db: Session = Depends(get_db)):
    """Show the registration form.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    db : Session
        Database session for optional session lookup.

    Returns
    -------
    TemplateResponse
        Rendered ``register.html``.
    RedirectResponse
        Redirects to ``/`` when already logged in.
    """
    user = get_current_user(request, db)
    if user is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    err = request.query_params.get("error")
    return templates.TemplateResponse(
        request,
        "register.html",
        {"error": err, "user": None},
    )


@router.post("/register")
async def register_post(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Session = Depends(get_db),
):
    """Create a new user account and establish a session.

    Parameters
    ----------
    request : Request
        Used to render ``register.html`` again when validation fails.
    username : str
        Desired login name.
    password : str
        Desired plaintext password (hashed before storage).
    db : Session
        Database session provided by dependency injection.

    Returns
    -------
    RedirectResponse
        Redirects to ``/welcome`` on success.
    TemplateResponse
        Re-renders ``register.html`` with an error when the name is taken
        or input is invalid. Database ``IntegrityError`` (duplicate
        username) is caught and mapped to this response.
    """
    name = username.strip()
    if not name or not password:
        auth_log.warning("Registration rejected empty username or password")
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "Username and password are required.",
                "user": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(username=name, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        auth_log.warning("Registration failed duplicate username=%s", name)
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": "That username is already taken.",
                "user": None,
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    db.refresh(user)
    auth_log.info("User registered username=%s user_id=%s", name, user.id)
    response = RedirectResponse(url="/welcome", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, user.id)
    return response


@router.get("/welcome")
async def welcome_get(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Choose starter template versus a blank notebook (one-time onboarding).

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    user : User
        Authenticated user from :func:`app.auth.require_auth`.
    db : Session
        Database session for checking existing topics.

    Returns
    -------
    TemplateResponse
        Renders ``welcome.html`` when the account has no topics yet.
    RedirectResponse
        Redirects to ``/`` if the user already has at least one topic.
    """
    if db.scalars(select(Topic.id).where(Topic.user_id == user.id)).first() is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "welcome.html",
        {"user": user, "error": None},
    )


@router.post("/welcome")
async def welcome_post(
    request: Request,
    choice: Annotated[str, Form()],
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Apply the onboarding choice then send the client to the home page.

    Parameters
    ----------
    request : Request
        Used to render ``welcome.html`` when validation fails.
    choice : str
        Form field ``choice``: ``template`` imports starter commands; ``blank``
        skips inserts.
    user : User
        Authenticated user from :func:`app.auth.require_auth`.
    db : Session
        Database session for inserting seeded rows.

    Returns
    -------
    RedirectResponse
        Redirects to ``/`` after a successful choice (or when topics already
        exist).
    TemplateResponse
        Re-renders ``welcome.html`` on invalid ``choice`` with HTTP 400.
    """
    if db.scalars(select(Topic.id).where(Topic.user_id == user.id)).first() is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    normalized = choice.strip().lower()
    if normalized not in ("template", "blank"):
        return templates.TemplateResponse(
            request,
            "welcome.html",
            {"user": user, "error": "Pick one of the two options."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if normalized == "template":
        populate_starter_data(db, user.id)
        db.commit()

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout_post(request: Request, db: Session = Depends(get_db)):
    """End the current session and return to the login page.

    Parameters
    ----------
    request : Request
        Incoming request (session cookie read for logging).
    db : Session
        Database session passed to :func:`app.auth.get_current_user`.

    Returns
    -------
    RedirectResponse
        Redirects to ``/login`` after clearing the session cookie.
    """
    user = get_current_user(request, db)
    if user is not None:
        auth_log.info("Logout user_id=%s", user.id)
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    _clear_session_cookie(response)
    return response
