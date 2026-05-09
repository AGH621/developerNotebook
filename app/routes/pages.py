"""HTML page routes: authentication and (later) home, welcome, and topic pages."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
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
from app.models import Section, Topic, User
from app.routes.sections import _topic_context_flags
from app.seed_data import STARTER_DATA
from app.services.seed import (
    populate_starter_data,
    starter_topic_indices_available,
    starter_topics_for_user,
)
from app.templating import templates

router = APIRouter()
auth_log = logging.getLogger("devnotebook.auth")


@router.get("/")
async def home(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List the authenticated user's topics ordered for the home grid.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    user : User
        Session user from :func:`app.auth.require_auth`.
    db : Session
        Database session from dependency injection.

    Returns
    -------
    TemplateResponse
        Renders ``home.html`` with the user's topics in display order.
    """
    topics = db.scalars(
        select(Topic)
        .where(Topic.user_id == user.id)
        .order_by(Topic.display_order.asc(), Topic.id.asc()),
    ).all()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"user": user, "topics": topics},
    )


@router.get("/topic/{slug}")
async def topic_detail(
    request: Request,
    slug: str,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Show one topic with its sections and command entries.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    slug : str
        URL slug for the topic (unique per user).
    user : User
        Authenticated owner from :func:`app.auth.require_auth`.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Renders ``topic.html`` with eagerly loaded sections and entries.
    Raises
    ------
    HTTPException
        **404** when no topic matches the slug for this user.
    """
    topic = db.scalars(
        select(Topic)
        .where(Topic.user_id == user.id, Topic.slug == slug)
        .options(
            selectinload(Topic.sections).selectinload(Section.entries),
        ),
    ).first()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    sections = sorted(topic.sections, key=lambda s: (s.display_order, s.id))
    hide_chrome, show_sidebar = _topic_context_flags(topic)
    return templates.TemplateResponse(
        request,
        "topic.html",
        {
            "user": user,
            "topic": topic,
            "sections": sections,
            "hide_section_chrome": hide_chrome,
            "show_section_sidebar": show_sidebar,
        },
    )


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
        {
            "user": user,
            "error": None,
            "starter_topics": starter_topics_for_user(db, user.id),
        },
    )


def _next_topic_display_order(db: Session, user_id: int) -> int:
    """First ``display_order`` value for a new topic appended to the notebook."""
    raw = db.scalar(
        select(func.coalesce(func.max(Topic.display_order), -1)).where(Topic.user_id == user_id),
    )
    return int(raw) + 1


def _parse_topic_indices(form_values: list[str], *, n_topics: int) -> frozenset[int]:
    """Return valid distinct starter topic indices from form ``topic`` fields."""
    seen: set[int] = set()
    for raw in form_values:
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n_topics:
            seen.add(i)
    return frozenset(seen)


@router.post("/welcome")
async def welcome_post(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Apply the onboarding choice then send the client to the home page.

    Parameters
    ----------
    request : Request
        Used to render ``welcome.html`` when validation fails. Form fields:
        ``choice`` (``template`` or ``blank``), and ``topic`` (repeated indices
        when ``choice`` is ``template``).
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

    form = await request.form()
    choice_raw = form.get("choice")
    normalized = str(choice_raw or "").strip().lower()
    starter_ctx = {"user": user, "starter_topics": starter_topics_for_user(db, user.id)}

    if normalized not in ("template", "blank"):
        return templates.TemplateResponse(
            request,
            "welcome.html",
            {**starter_ctx, "error": "Pick blank notebook or seed selected topics."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if normalized == "template":
        raw_topics = form.getlist("topic")
        topic_indices = _parse_topic_indices(
            [str(v) for v in raw_topics],
            n_topics=len(STARTER_DATA),
        )
        if not topic_indices:
            return templates.TemplateResponse(
                request,
                "welcome.html",
                {
                    **starter_ctx,
                    "error": "Choose at least one technology to seed, or start blank.",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        populate_starter_data(db, user.id, topic_indices=topic_indices)
        db.commit()

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/seed-topics")
async def seed_topics_get(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Pick bundled cheatsheets to add to an existing notebook."""
    return templates.TemplateResponse(
        request,
        "seed_topics.html",
        {
            "user": user,
            "error": None,
            "starter_topics": starter_topics_for_user(db, user.id),
        },
    )


@router.post("/seed-topics")
async def seed_topics_post(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Insert selected starter topics that the user does not already have."""
    form = await request.form()
    raw_topics = form.getlist("topic")
    topic_indices = _parse_topic_indices(
        [str(v) for v in raw_topics],
        n_topics=len(STARTER_DATA),
    )
    starter_ctx = {"user": user, "starter_topics": starter_topics_for_user(db, user.id)}

    if not topic_indices:
        return templates.TemplateResponse(
            request,
            "seed_topics.html",
            {
                **starter_ctx,
                "error": "Choose at least one technology to add.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    allowed = starter_topic_indices_available(db, user.id)
    to_seed = topic_indices & allowed
    if not to_seed:
        return templates.TemplateResponse(
            request,
            "seed_topics.html",
            {
                **starter_ctx,
                "error": "Those topics are already in your notebook.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    next_order = _next_topic_display_order(db, user.id)
    populate_starter_data(
        db,
        user.id,
        topic_indices=to_seed,
        display_order_start=next_order,
    )
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
