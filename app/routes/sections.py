"""Section CRUD routes (HTMX partials for the topic page)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_auth
from app.database import get_db
from app.models import Section, Topic, User
from app.routes.topics import _topic_owned, _topic_with_sections
from app.templating import templates

router = APIRouter()
sections_log = logging.getLogger("devnotebook.routes.sections")


def _topic_context_flags(topic: Topic) -> tuple[bool, bool]:
    """Compute topic-page booleans for section chrome and sidebar visibility.

    Parameters
    ----------
    topic : Topic
        Topic with ``sections`` relationship populated.

    Returns
    -------
    tuple of (bool, bool)
        ``hide_section_chrome`` when the topic has only one unnamed section
        (muted “Untitled section” heading; user can rename via Edit). ``show_section_sidebar`` is True when there are
        at least two named sections (anchor navigation).
    """
    secs = sorted(topic.sections, key=lambda s: (s.display_order, s.id))
    hide = len(secs) == 1 and secs[0].name is None
    named_n = sum(1 for s in secs if s.name)
    show_sidebar = named_n >= 2
    return hide, show_sidebar


def _sorted_sections(topic: Topic) -> list[Section]:
    return sorted(topic.sections, key=lambda s: (s.display_order, s.id))


def _section_bundle_response(request: Request, topic_loaded: Topic, section: Section):
    hide_chrome, show_sidebar = _topic_context_flags(topic_loaded)
    return templates.TemplateResponse(
        request,
        "partials/section_oob_bundle.html",
        {
            "topic": topic_loaded,
            "section": section,
            "hide_section_chrome": hide_chrome,
            "show_section_sidebar": show_sidebar,
            "sections": _sorted_sections(topic_loaded),
        },
    )


def _sidebar_oob_only(request: Request, topic_loaded: Topic):
    _, show_sidebar = _topic_context_flags(topic_loaded)
    return templates.TemplateResponse(
        request,
        "partials/topic_sidebar_oob.html",
        {
            "topic": topic_loaded,
            "show_section_sidebar": show_sidebar,
            "sections": _sorted_sections(topic_loaded),
        },
    )


def _section_owned(db: Session, section_id: int, user_id: int) -> Section | None:
    return db.scalars(
        select(Section)
        .join(Topic)
        .where(Section.id == section_id, Topic.user_id == user_id)
        .options(selectinload(Section.entries)),
    ).first()


@router.post("/topics/{topic_id}/sections")
async def create_section(
    request: Request,
    topic_id: int,
    name: Annotated[str | None, Form()] = None,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Append a named section to a topic owned by the current user.

    Parameters
    ----------
    request : Request
        Incoming request for template rendering.
    topic_id : int
        Parent topic primary key.
    name : str or None
        Display name from the ``name`` form field.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        New section markup plus sidebar ``hx-swap-oob`` when applicable.
    Response
        **404** when the topic is missing or not owned by ``user``.
    """
    topic = _topic_owned(db, topic_id, user.id)
    if topic is None:
        sections_log.warning(
            "Section create forbidden topic_id=%s user_id=%s",
            topic_id,
            user.id,
        )
        return Response(status_code=404)

    label = (name or "").strip() or "New section"
    next_ord = db.scalar(
        select(func.coalesce(func.max(Section.display_order), -1)).where(
            Section.topic_id == topic_id,
        ),
    )
    slot = int(next_ord) + 1 if next_ord is not None else 0
    section = Section(topic_id=topic_id, name=label, display_order=slot, notes=None)
    db.add(section)
    db.commit()
    section = _section_owned(db, section.id, user.id)
    if section is None:
        raise RuntimeError("Failed to load section after create")

    topic_loaded = _topic_with_sections(db, topic_id)
    if topic_loaded is None:
        raise RuntimeError("Failed to load topic after section create")
    sections_log.info("Section created id=%s topic_id=%s user_id=%s", section.id, topic_id, user.id)
    return _section_bundle_response(request, topic_loaded, section)


@router.get("/sections/{section_id}/edit")
async def section_edit_partial(
    request: Request,
    section_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return an inline edit form for a section heading and notes.

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    section_id : int
        Section primary key.
    user : User
        Authenticated notebook owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Renders ``partials/section_edit.html`` when authorized.
    Response
        **404** when the section does not belong to ``user``.
    """
    section = _section_owned(db, section_id, user.id)
    if section is None:
        sections_log.warning(
            "Section edit forbidden section_id=%s user_id=%s",
            section_id,
            user.id,
        )
        return Response(status_code=404)
    topic_loaded = _topic_with_sections(db, section.topic_id)
    if topic_loaded is None:
        return Response(status_code=404)
    hide_chrome, _ = _topic_context_flags(topic_loaded)
    return templates.TemplateResponse(
        request,
        "partials/section_edit.html",
        {
            "topic": topic_loaded,
            "section": section,
            "hide_section_chrome": hide_chrome,
        },
    )


@router.get("/sections/{section_id}/view")
async def section_view_partial(
    request: Request,
    section_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return the read-only section block (cancel after inline edit).

    Parameters
    ----------
    request : Request
        Incoming HTTP request.
    section_id : int
        Section primary key.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Renders ``partials/section.html`` when authorized.
    Response
        **404** when the section is absent or not owned.
    """
    section = _section_owned(db, section_id, user.id)
    if section is None:
        sections_log.warning(
            "Section view forbidden section_id=%s user_id=%s",
            section_id,
            user.id,
        )
        return Response(status_code=404)
    topic_loaded = _topic_with_sections(db, section.topic_id)
    if topic_loaded is None:
        return Response(status_code=404)
    return _section_bundle_response(request, topic_loaded, section)


@router.put("/sections/reorder")
async def reorder_sections(
    section_order: Annotated[str, Form()],
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Reorder sections within a topic from a SortableJS ID list.

    Parameters
    ----------
    section_order : str
        Comma-separated section IDs in presentation order.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    Response
        **204** on success, **400** when IDs are invalid or do not match a
        single topic's full set, **404** when ownership fails.
    """
    raw = [p.strip() for p in section_order.split(",") if p.strip()]
    try:
        ids_ordered = [int(x) for x in raw]
    except ValueError:
        sections_log.warning("Section reorder rejected bad ids user_id=%s", user.id)
        return Response(status_code=400)

    if not ids_ordered:
        sections_log.warning("Section reorder rejected empty ids user_id=%s", user.id)
        return Response(status_code=400)

    first = db.scalars(select(Section).where(Section.id == ids_ordered[0])).first()
    if first is None:
        return Response(status_code=404)

    topic = _topic_owned(db, first.topic_id, user.id)
    if topic is None:
        sections_log.warning(
            "Section reorder forbidden first_section=%s user_id=%s",
            ids_ordered[0],
            user.id,
        )
        return Response(status_code=404)

    owned = db.scalars(
        select(Section.id).where(Section.topic_id == topic.id),
    ).all()
    if set(ids_ordered) != set(owned) or len(ids_ordered) != len(owned):
        sections_log.warning(
            "Section reorder mismatched topic_id=%s user_id=%s",
            topic.id,
            user.id,
        )
        return Response(status_code=400)

    mapping = {sid: idx for idx, sid in enumerate(ids_ordered)}
    for sec in db.scalars(select(Section).where(Section.topic_id == topic.id)).all():
        sec.display_order = mapping[sec.id]
    db.commit()
    sections_log.info("Sections reordered topic_id=%s user_id=%s count=%s", topic.id, user.id, len(ids_ordered))
    return Response(status_code=204)


@router.put("/sections/{section_id}")
async def update_section(
    request: Request,
    section_id: int,
    name: Annotated[str, Form()],
    notes: Annotated[str | None, Form()] = None,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Rename a section and update optional notes text.

    Parameters
    ----------
    request : Request
        Used for templated responses.
    section_id : int
        Section to update.
    name : str
        New title; blank becomes ``None`` (unnamed default section label).
    notes : str or None
        Optional notes / callout body.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Updated section markup plus sidebar ``hx-swap-oob``.
    Response
        **404** when unauthorized or missing.
    """
    section = _section_owned(db, section_id, user.id)
    if section is None:
        sections_log.warning(
            "Section update forbidden section_id=%s user_id=%s",
            section_id,
            user.id,
        )
        return Response(status_code=404)

    label = (name or "").strip()
    section.name = label or None
    n = (notes or "").strip()
    section.notes = n or None
    db.commit()

    section = _section_owned(db, section_id, user.id)
    if section is None:
        return Response(status_code=404)

    topic_loaded = _topic_with_sections(db, section.topic_id)
    if topic_loaded is None:
        return Response(status_code=404)
    sections_log.info("Section updated id=%s topic_id=%s user_id=%s", section.id, section.topic_id, user.id)
    return _section_bundle_response(request, topic_loaded, section)


@router.delete("/sections/{section_id}")
async def delete_section(
    request: Request,
    section_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Delete a section and cascade-remove its entries.

    Parameters
    ----------
    section_id : int
        Section primary key.
    user : User
        Authenticated owner.
    db : Session
        Database session.

    Returns
    -------
    TemplateResponse
        Sidebar OOB fragment for HTMX; **404** when not allowed.

    Notes
    -----
    Primary ``hx-delete`` swap removes the section node; sidebar ``hx-swap-oob``
    in the body refreshes TOC visibility.
    """
    section = _section_owned(db, section_id, user.id)
    if section is None:
        sections_log.warning(
            "Section delete forbidden section_id=%s user_id=%s",
            section_id,
            user.id,
        )
        return Response(status_code=404)
    tid = section.topic_id
    db.delete(section)
    db.commit()
    topic_loaded = _topic_with_sections(db, tid)
    if topic_loaded is None:
        sections_log.warning("Topic missing after delete section_id=%s topic_id=%s", section_id, tid)
        return Response(status_code=404)
    sections_log.info("Section deleted id=%s topic_id=%s user_id=%s", section_id, tid, user.id)
    return _sidebar_oob_only(request, topic_loaded)
