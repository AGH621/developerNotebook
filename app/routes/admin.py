"""Admin suite: user management, invitations, and starter catalog editing."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import hash_password, require_admin, validate_password
from app.database import get_db
from app.invite_requests import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from app.models import (
    Invitation,
    InvitationRequest,
    StarterEntry,
    StarterSection,
    StarterTopic,
    Topic,
    User,
)
from app.settings import (
    get_app_settings,
    invalidate_settings_cache,
    validate_session_timeout_minutes,
)
from app.slug import allocate_starter_topic_slug
from app.templating import invite_register_url, templates

# include_in_schema=False hides routes from the OpenAPI document only; every path
# still enforces auth via require_admin — it is not an access-control mechanism.
router = APIRouter(prefix="/admin", tags=["admin"])
admin_log = logging.getLogger("devnotebook.routes.admin")


def _htmx_or_redirect(request: Request, url: str) -> Response:
    if (request.headers.get("HX-Request") or "").lower() == "true":
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _admin_count(db: Session) -> int:
    return int(db.scalar(select(func.count(User.id)).where(User.is_admin.is_(True))) or 0)


def _topic_count_for_user(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.count(Topic.id)).where(Topic.user_id == user_id)) or 0)


def _unique_invite_code(db: Session) -> str:
    for _ in range(12):
        raw = secrets.token_urlsafe(32)
        if len(raw) > 96:
            raw = raw[:96]
        exists = db.scalars(select(Invitation.id).where(Invitation.code == raw)).first()
        if exists is None:
            return raw
    raise HTTPException(status_code=500, detail="Could not allocate invite code")


@router.get("/ok")
async def admin_ok(user: User = Depends(require_admin)) -> dict[str, bool]:
    """Lightweight check that the session belongs to an administrator."""
    return {"ok": True, "is_admin": bool(user.is_admin)}


@router.get("", include_in_schema=False)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List accounts with notebook size and moderation actions."""
    users = db.scalars(select(User).order_by(User.username.asc())).all()
    rows: list[dict[str, object]] = []
    for u in users:
        rows.append(
            {
                "user": u,
                "topic_count": _topic_count_for_user(db, u.id),
                "is_self": u.id == admin_user.id,
            },
        )

    qp_error = request.query_params.get("error")
    qp_ok = request.query_params.get("ok")
    app_settings = get_app_settings(db)
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": admin_user,
            "user_rows": rows,
            "error": qp_error,
            "ok_message": qp_ok,
            "now_utc": datetime.now(timezone.utc).replace(tzinfo=None),
            "app_settings": app_settings,
        },
    )


@router.post("/settings/session-timeouts", include_in_schema=False)
async def admin_update_session_timeouts(
    session_absolute_minutes: Annotated[int, Form()],
    session_idle_minutes: Annotated[int, Form()],
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Update absolute and idle session timeout values."""
    err = validate_session_timeout_minutes(
        session_absolute_minutes,
        session_idle_minutes,
    )
    if err:
        return RedirectResponse(
            url="/admin?error=" + quote(err),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    settings = get_app_settings(db)
    settings.session_absolute_minutes = session_absolute_minutes
    settings.session_idle_minutes = session_idle_minutes
    db.commit()
    invalidate_settings_cache()
    admin_log.info(
        "admin=%s updated session timeouts absolute=%s idle=%s",
        admin_user.id,
        session_absolute_minutes,
        session_idle_minutes,
    )
    return RedirectResponse(
        url="/admin?ok=" + quote("Session timeouts updated."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/users/{user_id}/suspend", include_in_schema=False)
async def admin_toggle_suspend(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    if user_id == admin_user.id:
        return RedirectResponse(
            url="/admin?error=" + quote("You cannot suspend your own account."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.is_suspended:
        target.is_suspended = False
        msg = quote(f"Account {target.username} is active again.")
    else:
        if target.is_admin and _admin_count(db) == 1:
            return RedirectResponse(
                url="/admin?error="
                + quote("Cannot suspend the only administrator."),
                status_code=status.HTTP_303_SEE_OTHER,
            )
        target.is_suspended = True
        target.session_version += 1
        msg = quote(f"Account {target.username} has been suspended.")
    db.commit()
    admin_log.info(
        "admin=%s toggled suspend user_id=%s now=%s",
        admin_user.id,
        target.id,
        target.is_suspended,
    )
    return RedirectResponse(url="/admin?ok=" + msg, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/unlock", include_in_schema=False)
async def admin_unlock_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    target.failed_login_count = 0
    target.locked_until = None
    db.commit()
    admin_log.info("admin=%s unlocked user_id=%s", admin_user.id, target.id)
    ok = quote(f"Account {target.username} has been unlocked.")
    return RedirectResponse(url="/admin?ok=" + ok, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete", include_in_schema=False)
async def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    if user_id == admin_user.id:
        return RedirectResponse(
            url="/admin?error=" + quote("You cannot delete your own account."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if target.is_guest:
        return RedirectResponse(
            url="/admin?error=" + quote("The shared guest account cannot be deleted."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if target.is_admin and _admin_count(db) == 1:
        return RedirectResponse(
            url="/admin?error=" + quote("Cannot delete the sole administrator."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    uname = target.username
    db.delete(target)
    db.commit()
    admin_log.warning("admin=%s deleted user_id=%s username=%s", admin_user.id, user_id, uname)
    ok = quote(f"Deleted user {uname}.")
    return RedirectResponse(url="/admin?ok=" + ok, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/{user_id}/password", include_in_schema=False)
async def admin_password_form(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    qp_error = request.query_params.get("error")
    return templates.TemplateResponse(
        request,
        "admin/password_form.html",
        {"user": admin_user, "target_user": target, "error": qp_error},
    )


@router.post("/users/{user_id}/password", include_in_schema=False)
async def admin_password_set(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
    new_password: Annotated[str | None, Form()] = None,
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    pw = (new_password or "").strip()
    if not pw:
        err = quote("Password cannot be empty.")
        return RedirectResponse(
            url=f"/admin/users/{user_id}/password?error={err}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    pw_err = validate_password(pw)
    if pw_err:
        err = quote(pw_err)
        return RedirectResponse(
            url=f"/admin/users/{user_id}/password?error={err}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target.password_hash = hash_password(pw)
    target.session_version += 1
    db.commit()
    admin_log.info("admin=%s reset password user_id=%s", admin_user.id, target.id)
    ok = quote(f"Password updated for {target.username}.")
    return RedirectResponse(url="/admin?ok=" + ok, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/invites", include_in_schema=False)
async def admin_invites(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    invites = db.scalars(
        select(Invitation).order_by(Invitation.created_at.desc()),
    ).all()
    qp_error = request.query_params.get("error")
    qp_ok = request.query_params.get("ok")
    created_code = request.query_params.get("created")
    new_link = (
        invite_register_url(request, created_code.strip())
        if created_code and created_code.strip()
        else None
    )
    return templates.TemplateResponse(
        request,
        "admin/invites.html",
        {
            "user": admin_user,
            "invitations": invites,
            "error": qp_error,
            "ok_message": qp_ok,
            "new_invite_link": new_link,
        },
    )


@router.post("/invites", include_in_schema=False)
async def admin_invites_create(
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    code = _unique_invite_code(db)
    inv = Invitation(code=code, created_by=admin_user.id)
    db.add(inv)
    db.commit()
    admin_log.info("admin=%s created invitation id=%s", admin_user.id, inv.id)
    return RedirectResponse(
        url="/admin/invites?created=" + quote(code, safe=""),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/invites/{invitation_id}/revoke", include_in_schema=False)
async def admin_invites_revoke(
    invitation_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    inv = db.get(Invitation, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")

    if inv.used_by is not None:
        return RedirectResponse(
            url="/admin/invites?error="
            + quote("That invitation has already been used."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    db.delete(inv)
    db.commit()
    admin_log.info("admin=%s revoked invitation id=%s", admin_user.id, invitation_id)
    return RedirectResponse(
        url="/admin/invites?ok="
        + quote("Invitation revoked."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _pending_invite_request_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(InvitationRequest.id)).where(
                InvitationRequest.status == STATUS_PENDING,
            ),
        )
        or 0,
    )


@router.get("/invite-requests", include_in_schema=False)
async def admin_invite_requests(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """List visitor invitation requests for review."""
    requests = db.scalars(
        select(InvitationRequest)
        .options(selectinload(InvitationRequest.invitation))
        .order_by(
            case((InvitationRequest.status == STATUS_PENDING, 0), else_=1),
            InvitationRequest.created_at.desc(),
        ),
    ).all()
    qp_error = request.query_params.get("error")
    qp_ok = request.query_params.get("ok")
    approved_id_raw = request.query_params.get("approved")
    created_code = request.query_params.get("created")
    approved_email: str | None = None
    new_link: str | None = None
    if approved_id_raw and approved_id_raw.strip().isdigit():
        approved_row = db.get(InvitationRequest, int(approved_id_raw))
        if approved_row is not None:
            approved_email = approved_row.email
    if created_code and created_code.strip():
        new_link = invite_register_url(request, created_code.strip())
    return templates.TemplateResponse(
        request,
        "admin/invite_requests.html",
        {
            "user": admin_user,
            "invite_requests": requests,
            "pending_count": _pending_invite_request_count(db),
            "error": qp_error,
            "ok_message": qp_ok,
            "approved_email": approved_email,
            "new_invite_link": new_link,
        },
    )


@router.post("/invite-requests/{request_id}/approve", include_in_schema=False)
async def admin_invite_requests_approve(
    request_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Approve a pending request and mint a single-use invitation."""
    req = db.get(InvitationRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Invitation request not found")

    if req.status != STATUS_PENDING:
        return RedirectResponse(
            url="/admin/invite-requests?error="
            + quote("That request has already been reviewed."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    code = _unique_invite_code(db)
    inv = Invitation(code=code, created_by=admin_user.id)
    db.add(inv)
    db.flush()
    req.status = STATUS_APPROVED
    req.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    req.reviewed_by = admin_user.id
    req.invitation_id = inv.id
    db.commit()
    admin_log.info(
        "admin=%s approved invite request id=%s invitation_id=%s",
        admin_user.id,
        request_id,
        inv.id,
    )
    return RedirectResponse(
        url="/admin/invite-requests?approved="
        + quote(str(request_id), safe="")
        + "&created="
        + quote(code, safe=""),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/invite-requests/{request_id}/reject", include_in_schema=False)
async def admin_invite_requests_reject(
    request_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    """Reject a pending invitation request."""
    req = db.get(InvitationRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Invitation request not found")

    if req.status != STATUS_PENDING:
        return RedirectResponse(
            url="/admin/invite-requests?error="
            + quote("That request has already been reviewed."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    req.status = STATUS_REJECTED
    req.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    req.reviewed_by = admin_user.id
    db.commit()
    admin_log.info("admin=%s rejected invite request id=%s", admin_user.id, request_id)
    return RedirectResponse(
        url="/admin/invite-requests?ok=" + quote("Request rejected."),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _starter_topics(db: Session) -> list[StarterTopic]:
    return list(
        db.scalars(
            select(StarterTopic)
            .options(
                selectinload(StarterTopic.sections).selectinload(StarterSection.entries),
            )
            .order_by(StarterTopic.display_order.asc(), StarterTopic.id.asc()),
        ).all(),
    )


@router.get("/starter", include_in_schema=False)
async def admin_starter_get(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    topics_with = _starter_topics(db)
    for t in topics_with:
        t.sections.sort(key=lambda s: (s.display_order, s.id))
        for s in t.sections:
            s.entries.sort(key=lambda e: (e.display_order, e.id))
    topics_with.sort(key=lambda t: (t.name.casefold(), t.id))
    qp_err = request.query_params.get("error")
    qp_ok = request.query_params.get("ok")
    return templates.TemplateResponse(
        request,
        "admin/starter.html",
        {
            "user": admin_user,
            "starter_topics": topics_with,
            "error": qp_err,
            "ok_message": qp_ok,
        },
    )


@router.post("/starter/topics", include_in_schema=False)
async def admin_starter_add_topic(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    name: Annotated[str | None, Form()] = None,
):
    label = (name or "").strip() or "New topic"
    next_ord = db.scalar(select(func.coalesce(func.max(StarterTopic.display_order), -1)))
    slot = int(next_ord) + 1 if next_ord is not None else 0
    topic = StarterTopic(
        name=label,
        slug=allocate_starter_topic_slug(db, label),
        display_order=slot,
    )
    db.add(topic)
    db.commit()
    frag = f"#admin-starter-topic-{topic.id}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


def _starter_topic_save_response(
    request: Request,
    db: Session,
    topic_id: int,
    name: str | None,
) -> Response:
    topic = db.get(StarterTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Starter topic not found")
    lab = (name or "").strip()
    if lab:
        topic.name = lab
        topic.slug = allocate_starter_topic_slug(db, lab, exclude_topic_id=topic.id)
    db.commit()
    frag = f"#admin-starter-topic-{topic_id}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


@router.put("/starter/topics/{topic_id}", include_in_schema=False)
async def admin_starter_rename_topic(
    request: Request,
    topic_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    name: Annotated[str | None, Form()] = None,
):
    return _starter_topic_save_response(request, db, topic_id, name)


@router.post("/starter/topics/{topic_id}/save", include_in_schema=False)
async def admin_starter_save_topic_form(
    request: Request,
    topic_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    name: Annotated[str | None, Form()] = None,
):
    return _starter_topic_save_response(request, db, topic_id, name)


@router.post("/starter/topics/{topic_id}/guest-visible", include_in_schema=False)
async def admin_starter_set_guest_visible(
    topic_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    guest_visible: Annotated[str | None, Form()] = None,
):
    """Toggle whether a starter topic appears in the read-only guest catalog."""
    topic = db.get(StarterTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Starter topic not found")
    topic.guest_visible = (guest_visible or "").strip().lower() in ("1", "true", "on", "yes")
    db.commit()
    return Response(status_code=204)


def _starter_topic_delete_response(request: Request, db: Session, topic_id: int) -> Response:
    topic = db.get(StarterTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Starter topic not found")
    db.delete(topic)
    db.commit()
    return _htmx_or_redirect(request, "/admin/starter#admin-starter-catalog")


@router.delete("/starter/topics/{topic_id}", include_in_schema=False)
async def admin_starter_delete_topic(
    request: Request,
    topic_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return _starter_topic_delete_response(request, db, topic_id)


@router.post("/starter/topics/{topic_id}/delete", include_in_schema=False)
async def admin_starter_delete_topic_submit(
    request: Request,
    topic_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return _starter_topic_delete_response(request, db, topic_id)


@router.post("/starter/topics/{topic_id}/sections", include_in_schema=False)
async def admin_starter_add_section(
    request: Request,
    topic_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    name: Annotated[str | None, Form()] = None,
):
    topic = db.get(StarterTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Starter topic not found")

    lbl = (name or "").strip()
    section_name: str | None = lbl or None
    next_ord = db.scalar(
        select(func.coalesce(func.max(StarterSection.display_order), -1)).where(
            StarterSection.topic_id == topic_id,
        ),
    )
    slot = int(next_ord) + 1 if next_ord is not None else 0
    sec = StarterSection(topic_id=topic_id, name=section_name, display_order=slot, notes=None)
    db.add(sec)
    db.commit()
    frag = f"#admin-starter-section-{sec.id}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


def _starter_section_save_response(
    request: Request,
    db: Session,
    section_id: int,
    name: str | None,
    notes: str | None,
) -> Response:
    sec = db.get(StarterSection, section_id)
    if sec is None:
        raise HTTPException(status_code=404, detail="Starter section not found")

    lbl = (name or "").strip()
    sec.name = lbl or None
    ntxt = (notes or "").strip()
    sec.notes = ntxt or None
    db.commit()
    frag = f"#admin-starter-section-{section_id}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


@router.put("/starter/sections/{section_id}", include_in_schema=False)
async def admin_starter_edit_section(
    request: Request,
    section_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    name: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
):
    return _starter_section_save_response(request, db, section_id, name, notes)


@router.post("/starter/sections/{section_id}/save", include_in_schema=False)
async def admin_starter_save_section_form(
    request: Request,
    section_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    name: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
):
    return _starter_section_save_response(request, db, section_id, name, notes)


def _starter_section_delete_response(request: Request, db: Session, section_id: int) -> Response:
    sec = db.get(StarterSection, section_id)
    if sec is None:
        raise HTTPException(status_code=404, detail="Starter section not found")
    topic_anchor = sec.topic_id
    db.delete(sec)
    db.commit()
    frag = f"#admin-starter-topic-{topic_anchor}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


@router.delete("/starter/sections/{section_id}", include_in_schema=False)
async def admin_starter_delete_section(
    request: Request,
    section_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return _starter_section_delete_response(request, db, section_id)


@router.post("/starter/sections/{section_id}/delete", include_in_schema=False)
async def admin_starter_delete_section_submit(
    request: Request,
    section_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return _starter_section_delete_response(request, db, section_id)


@router.post("/starter/sections/{section_id}/entries", include_in_schema=False)
async def admin_starter_add_entry(
    request: Request,
    section_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    description: Annotated[str | None, Form()] = None,
    command: Annotated[str | None, Form()] = None,
):
    sec = db.get(StarterSection, section_id)
    if sec is None:
        raise HTTPException(status_code=404, detail="Starter section not found")

    desc = (description or "").strip() or "Description"
    cmd = (command or "").strip() or "command"
    next_ord = db.scalar(
        select(func.coalesce(func.max(StarterEntry.display_order), -1)).where(
            StarterEntry.section_id == section_id,
        ),
    )
    slot = int(next_ord) + 1 if next_ord is not None else 0
    ent = StarterEntry(section_id=section_id, description=desc, command=cmd, display_order=slot)
    db.add(ent)
    db.commit()
    frag = f"#admin-starter-entry-{ent.id}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


def _starter_entry_save_response(
    request: Request,
    db: Session,
    entry_id: int,
    description: str | None,
    command: str | None,
) -> Response:
    ent = db.get(StarterEntry, entry_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Starter entry not found")

    ent.description = (description or "").strip() or ent.description
    ent.command = (command or "").strip() or ent.command
    db.commit()
    frag = f"#admin-starter-entry-{entry_id}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


@router.put("/starter/entries/{entry_id}", include_in_schema=False)
async def admin_starter_edit_entry(
    request: Request,
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    description: Annotated[str | None, Form()] = None,
    command: Annotated[str | None, Form()] = None,
):
    return _starter_entry_save_response(request, db, entry_id, description, command)


@router.post("/starter/entries/{entry_id}/save", include_in_schema=False)
async def admin_starter_save_entry_form(
    request: Request,
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    description: Annotated[str | None, Form()] = None,
    command: Annotated[str | None, Form()] = None,
):
    """POST variant for Save (classic form + 303 + anchor); same logic as PUT."""
    return _starter_entry_save_response(request, db, entry_id, description, command)


def _starter_entry_delete_response(request: Request, db: Session, entry_id: int) -> Response:
    ent = db.get(StarterEntry, entry_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Starter entry not found")
    section_anchor = ent.section_id
    db.delete(ent)
    db.commit()
    frag = f"#admin-starter-section-{section_anchor}"
    return _htmx_or_redirect(request, "/admin/starter" + frag)


@router.delete("/starter/entries/{entry_id}", include_in_schema=False)
async def admin_starter_delete_entry(
    request: Request,
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return _starter_entry_delete_response(request, db, entry_id)


@router.post("/starter/entries/{entry_id}/delete", include_in_schema=False)
async def admin_starter_delete_entry_submit(
    request: Request,
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """POST variant so Remove can use a normal form (303 redirect, no HTMX)."""
    return _starter_entry_delete_response(request, db, entry_id)
