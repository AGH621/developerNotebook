"""HTML page routes: authentication and (later) home, welcome, and topic pages."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
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
    session_cookie_secure,
    validate_password,
    verify_password,
)
from app.database import get_db
from app.rate_limit import limiter
from app.models import Invitation, Section, Topic, User
from app.routes.sections import _topic_context_flags
from app.services.seed import (
    populate_starter_data,
    starter_catalog_topic_count,
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
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=session_cookie_secure(),
    )


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
@limiter.limit("5/minute")
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

    _LOCKOUT_THRESHOLD = 11
    _LOCKOUT_DURATION = timedelta(minutes=30)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    if row.locked_until and row.locked_until > now_utc:
        auth_log.warning("Login blocked locked account username=%s user_id=%s", name, row.id)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Account temporarily locked due to too many failed attempts. Try again later.",
                "user": None,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if not verify_password(password, row.password_hash):
        row.failed_login_count += 1
        if row.failed_login_count >= _LOCKOUT_THRESHOLD:
            row.locked_until = now_utc + _LOCKOUT_DURATION
            auth_log.warning(
                "Account locked username=%s user_id=%s after %d failures",
                name, row.id, row.failed_login_count,
            )
        else:
            auth_log.warning("Login failed bad password username=%s", name)
        db.commit()
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Unknown username or incorrect password.",
                "user": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if row.is_suspended:
        auth_log.warning("Login blocked suspended username=%s user_id=%s", name, row.id)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "This account has been suspended. Contact an administrator.",
                "user": None,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    row.failed_login_count = 0
    row.locked_until = None
    db.commit()
    auth_log.info("Login succeeded username=%s user_id=%s", name, row.id)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, row)
    return response


@router.get("/register")
async def register_get(
    request: Request,
    db: Session = Depends(get_db),
    code: Annotated[str | None, Query()] = None,
):
    """Show the registration form when ``?code=`` matches an unused invitation.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    db : Session
        Database session for optional session lookup.
    code : str or None
        Invitation token from ``/register?code=…``.

    Returns
    -------
    TemplateResponse
        Rendered ``register.html`` with or without the signup form.
    RedirectResponse
        Redirects to ``/`` when already logged in.
    """
    user = get_current_user(request, db)
    if user is not None:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    qp_error = request.query_params.get("error")
    ctx_base = {"user": None, "invite_code": None, "show_register_form": False}
    if qp_error:
        return templates.TemplateResponse(
            request,
            "register.html",
            {**ctx_base, "error": qp_error},
        )

    raw_code = (code or "").strip()
    if not raw_code:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                **ctx_base,
                "error": "Registration is by invitation only. Use the link from your invitation.",
            },
        )

    invitation = db.scalars(
        select(Invitation).where(
            Invitation.code == raw_code,
            Invitation.used_by.is_(None),
        ),
    ).first()
    if invitation is None:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                **ctx_base,
                "error": "This invitation link is invalid or has already been used.",
            },
        )

    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "user": None,
            "error": None,
            "show_register_form": True,
            "invite_code": raw_code,
        },
    )


@router.post("/register")
@limiter.limit("5/minute")
async def register_post(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    invite_code: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
):
    """Create a new user account and establish a session.

    Requires a valid, unused invitation matched by ``invite_code``.
    """

    def _invite_error_response(msg: str, *, status_cd: int) -> Response:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": msg,
                "user": None,
                "show_register_form": False,
                "invite_code": None,
            },
            status_code=status_cd,
        )

    name = username.strip()
    code_value = (invite_code or "").strip()
    if not name or not password:
        auth_log.warning("Registration rejected empty username or password")
        return _invite_error_response("Username and password are required.", status_cd=status.HTTP_400_BAD_REQUEST)

    invitation = db.scalars(
        select(Invitation).where(
            Invitation.code == code_value,
            Invitation.used_by.is_(None),
        ),
    ).first()
    if invitation is None:
        auth_log.warning("Registration rejected invalid or spent invite code")
        return _invite_error_response(
            "This invitation is invalid or has already been used.",
            status_cd=status.HTTP_409_CONFLICT,
        )

    pw_err = validate_password(password)
    if pw_err:
        auth_log.warning("Registration rejected weak password username=%s", name)
        return _invite_error_response(pw_err, status_cd=status.HTTP_400_BAD_REQUEST)

    user = User(username=name, password_hash=hash_password(password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        auth_log.warning("Registration failed duplicate username=%s", name)
        return _invite_error_response(
            "That username is already taken.",
            status_cd=status.HTTP_409_CONFLICT,
        )

    invitation.used_by = user.id
    invitation.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    db.refresh(user)
    auth_log.info("User registered username=%s user_id=%s", name, user.id)
    response = RedirectResponse(url="/welcome", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, user)
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
            n_topics=starter_catalog_topic_count(db),
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
        n_topics=starter_catalog_topic_count(db),
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
