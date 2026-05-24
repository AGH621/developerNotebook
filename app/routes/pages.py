"""HTML page routes: authentication and (later) home, welcome, and topic pages."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.responses import Response

from app.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    get_current_user,
    hash_password,
    require_auth,
    require_can_write,
    session_cookie_secure,
    validate_password,
    verify_password,
)
from app.database import get_db
from app.invite_requests import (
    STATUS_PENDING,
    normalize_email,
    normalize_optional_text,
    validate_request_email,
)
from app.rate_limit import limiter
from app.models import Invitation, InvitationRequest, Section, Topic, User
from app.validation import MAX_USERNAME, truncate
from app.routes.sections import _topic_context_flags
from app.services.guest import guest_topic_by_slug, guest_visible_topics, sorted_starter_sections
from app.services.seed import (
    populate_starter_data,
    starter_catalog_topic_count,
    starter_topic_indices_available,
    starter_topics_for_user,
)
from app.templating import templates

router = APIRouter()
auth_log = logging.getLogger("devnotebook.auth")


def _guest_login_available(db: Session) -> bool:
    return db.scalars(select(User.id).where(User.is_guest.is_(True))).first() is not None


def _login_template_ctx(db: Session, **extra: object) -> dict[str, object]:
    return {
        "user": None,
        "guest_available": _guest_login_available(db),
        **extra,
    }


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
    if user.is_guest:
        topics = guest_visible_topics(db)
    else:
        topics = db.scalars(
            select(Topic)
            .where(Topic.user_id == user.id)
            .order_by(Topic.display_order.asc(), Topic.id.asc()),
        ).all()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"user": user, "topics": topics, "read_only": user.is_guest},
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
    read_only = user.is_guest
    if user.is_guest:
        starter = guest_topic_by_slug(db, slug)
        if starter is None:
            raise HTTPException(status_code=404, detail="Topic not found")
        sections = sorted_starter_sections(starter)
        for section in sections:
            section.entries = sorted(
                section.entries,
                key=lambda e: (e.display_order, e.id),
            )
        hide_chrome, show_sidebar = _topic_context_flags(starter)
        return templates.TemplateResponse(
            request,
            "topic.html",
            {
                "user": user,
                "topic": starter,
                "sections": sections,
                "hide_section_chrome": hide_chrome,
                "show_section_sidebar": show_sidebar,
                "read_only": True,
            },
        )

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
            "read_only": read_only,
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
    ok = request.query_params.get("ok")
    guest_available = _guest_login_available(db)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": err, "ok": ok, "user": None, "guest_available": guest_available},
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
            _login_template_ctx(db, error="Username and password are required."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    row = db.scalars(select(User).where(User.username == name)).first()
    if row is None:
        auth_log.warning("Login failed unknown user username=%s", name)
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_template_ctx(db, error="Unknown username or incorrect password."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if row.is_guest:
        auth_log.warning("Login rejected password attempt for guest account username=%s", name)
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_template_ctx(
                db,
                error="Use Browse as guest on this page instead of signing in as the guest account.",
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    _LOCKOUT_THRESHOLD = 11
    _LOCKOUT_DURATION = timedelta(minutes=30)

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    if row.locked_until and row.locked_until > now_utc:
        auth_log.warning("Login blocked locked account username=%s user_id=%s", name, row.id)
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_template_ctx(
                db,
                error="Account temporarily locked due to too many failed attempts. Try again later.",
            ),
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
            _login_template_ctx(db, error="Unknown username or incorrect password."),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if row.is_suspended:
        auth_log.warning("Login blocked suspended username=%s user_id=%s", name, row.id)
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_template_ctx(
                db,
                error="This account has been suspended. Contact an administrator.",
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    row.failed_login_count = 0
    row.locked_until = None
    db.commit()
    auth_log.info("Login succeeded username=%s user_id=%s", name, row.id)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, row, db)
    return response


@router.post("/guest-login")
@limiter.limit("10/minute")
async def guest_login_post(
    request: Request,
    db: Session = Depends(get_db),
):
    """Start a read-only session as the shared guest account."""
    guest = db.scalars(select(User).where(User.is_guest.is_(True))).first()
    if guest is None:
        auth_log.warning("Guest login failed: no guest account configured")
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_template_ctx(db, error="Guest browsing is not available right now."),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if guest.is_suspended:
        auth_log.warning("Guest login blocked suspended guest user_id=%s", guest.id)
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_template_ctx(
                db,
                error="Guest browsing is temporarily unavailable. Contact an administrator.",
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )

    auth_log.info("Guest login succeeded user_id=%s username=%s", guest.id, guest.username)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, guest, db)
    return response


def _request_invite_nav_user(request: Request, db: Session) -> User | None:
    user = get_current_user(request, db)
    if user is not None and user.is_guest:
        return user
    return None


def _request_invite_template_ctx(
    *,
    user: User | None,
    error: str | None = None,
    success: str | None = None,
) -> dict[str, object]:
    return {
        "user": user,
        "error": error,
        "success": success,
        "show_form": success is None,
    }


@router.get("/request-invite")
async def request_invite_get(
    request: Request,
    db: Session = Depends(get_db),
):
    """Show the invitation request form."""
    user = get_current_user(request, db)
    if user is not None and not user.is_guest:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "request_invite.html",
        _request_invite_template_ctx(user=_request_invite_nav_user(request, db)),
    )


@router.post("/request-invite")
@limiter.limit("3/minute")
async def request_invite_post(
    request: Request,
    email: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    message: Annotated[str, Form()] = "",
    website: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
):
    """Accept a visitor invitation request for admin review."""
    nav_user = _request_invite_nav_user(request, db)
    ctx = _request_invite_template_ctx(user=nav_user)

    if website.strip():
        return templates.TemplateResponse(
            request,
            "request_invite.html",
            _request_invite_template_ctx(
                user=nav_user,
                success="Thanks — we'll review your request and contact you if approved.",
            ),
        )

    normalized_email = normalize_email(email)
    email_err = validate_request_email(normalized_email)
    if email_err:
        return templates.TemplateResponse(
            request,
            "request_invite.html",
            {**ctx, "error": email_err},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    existing = db.scalars(
        select(InvitationRequest.id).where(
            InvitationRequest.email == normalized_email,
            InvitationRequest.status == STATUS_PENDING,
        ),
    ).first()
    if existing is not None:
        return templates.TemplateResponse(
            request,
            "request_invite.html",
            {
                **ctx,
                "error": "You already have a pending request for that email address.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    req = InvitationRequest(
        email=normalized_email,
        name=normalize_optional_text(name, 150),
        message=normalize_optional_text(message, 2000),
        status=STATUS_PENDING,
    )
    db.add(req)
    db.commit()

    return templates.TemplateResponse(
        request,
        "request_invite.html",
        _request_invite_template_ctx(
            user=nav_user,
            success=(
                f"Thanks — we'll review your request and contact you at "
                f"{normalized_email} if approved."
            ),
        ),
    )


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
        Redirects to ``/`` when already logged in as a full account.
    """
    user = get_current_user(request, db)
    if user is not None and not user.is_guest:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    nav_user = user if user is not None and user.is_guest else None
    qp_error = request.query_params.get("error")
    ctx_base = {"user": nav_user, "invite_code": None, "show_register_form": False}
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
            "user": nav_user,
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
    session_user = get_current_user(request, db)
    nav_user = session_user if session_user is not None and session_user.is_guest else None

    def _invite_error_response(msg: str, *, status_cd: int) -> Response:
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": msg,
                "user": nav_user,
                "show_register_form": False,
                "invite_code": None,
            },
            status_code=status_cd,
        )

    name = truncate(username, MAX_USERNAME)
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

    rows_claimed = db.execute(
        update(Invitation)
        .where(Invitation.id == invitation.id, Invitation.used_by.is_(None))
        .values(used_by=user.id, used_at=datetime.now(timezone.utc).replace(tzinfo=None)),
    ).rowcount
    if not rows_claimed:
        db.rollback()
        auth_log.warning("Registration rejected invite race code=%s", code_value)
        return _invite_error_response(
            "This invitation is invalid or has already been used.",
            status_cd=status.HTTP_409_CONFLICT,
        )
    db.commit()

    db.refresh(user)
    auth_log.info("User registered username=%s user_id=%s", name, user.id)
    response = RedirectResponse(url="/welcome", status_code=status.HTTP_303_SEE_OTHER)
    create_session(response, user, db)
    return response


@router.get("/welcome")
async def welcome_get(
    request: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Choose starter template versus a blank notebook (one-time onboarding)."""
    if user.is_guest:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
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
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
):
    """Apply the onboarding choice then send the client to the home page."""
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
    if user.is_guest:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
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
    user: User = Depends(require_can_write),
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


@router.get("/change-password")
async def change_password_get(
    request: Request,
    user: User = Depends(require_auth),
):
    """Show the change-password form for the logged-in user."""
    if user.is_guest:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    ok = request.query_params.get("ok")
    return templates.TemplateResponse(
        request,
        "change_password.html",
        {"user": user, "error": None, "success": ok == "1"},
    )


@router.post("/change-password")
async def change_password_post(
    request: Request,
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
    current_password: Annotated[str, Form()] = "",
    new_password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
):
    """Update the logged-in user's password after verifying the current one."""
    ctx = {"user": user, "error": None, "success": False}

    if not current_password or not new_password or not confirm_password:
        ctx["error"] = "All fields are required."
        return templates.TemplateResponse(
            request,
            "change_password.html",
            ctx,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not verify_password(current_password, user.password_hash):
        auth_log.warning("Change password failed bad current password user_id=%s", user.id)
        ctx["error"] = "Current password is incorrect."
        return templates.TemplateResponse(
            request,
            "change_password.html",
            ctx,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if new_password != confirm_password:
        ctx["error"] = "New password and confirmation do not match."
        return templates.TemplateResponse(
            request,
            "change_password.html",
            ctx,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    pw_err = validate_password(new_password)
    if pw_err:
        ctx["error"] = pw_err
        return templates.TemplateResponse(
            request,
            "change_password.html",
            ctx,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user.password_hash = hash_password(new_password)
    user.session_version += 1
    db.commit()
    auth_log.info("Password changed user_id=%s", user.id)
    response = RedirectResponse(
        url="/change-password?ok=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    create_session(response, user, db)
    return response


@router.get("/delete-account")
async def delete_account_get(
    request: Request,
    user: User = Depends(require_auth),
):
    """Show account deletion confirmation (password required to proceed)."""
    if user.is_guest:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    if user.is_admin:
        return RedirectResponse(
            url="/change-password",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return templates.TemplateResponse(
        request,
        "delete_account.html",
        {"user": user, "error": None},
    )


@router.post("/delete-account")
async def delete_account_post(
    request: Request,
    user: User = Depends(require_can_write),
    db: Session = Depends(get_db),
    password: Annotated[str, Form()] = "",
):
    """Permanently delete the logged-in account after password confirmation."""
    if not password:
        return templates.TemplateResponse(
            request,
            "delete_account.html",
            {"user": user, "error": "Password is required to confirm deletion."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not verify_password(password, user.password_hash):
        auth_log.warning("Delete account failed bad password user_id=%s", user.id)
        return templates.TemplateResponse(
            request,
            "delete_account.html",
            {"user": user, "error": "Password is incorrect."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if user.is_admin:
        return templates.TemplateResponse(
            request,
            "delete_account.html",
            {
                "user": user,
                "error": "Administrator accounts cannot be deleted here.",
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    uname = user.username
    user_id = user.id
    db.delete(user)
    db.commit()
    auth_log.warning("User deleted own account user_id=%s username=%s", user_id, uname)
    response = RedirectResponse(
        url="/login?ok=" + quote("Your account has been deleted."),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _clear_session_cookie(response)
    return response


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
